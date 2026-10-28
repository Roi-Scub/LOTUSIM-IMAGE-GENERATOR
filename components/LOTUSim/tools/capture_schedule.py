"""Pure simulated-time capture scheduling; never sleeps or renders an image.

Explicit requests quantize each absolute instant independently, half-up to the
nearest source frame. Omitted requests retain legacy frame schedules exactly.
"""

import copy
from fractions import Fraction
import hashlib
import json
import math

SCHEMA = 'lotusim-capture-schedule-1'
MAX_CAPTURES = 2000
MAX_DURATION = 600


def _hash(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def _real(value, name):
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except (OverflowError, ValueError):
        valid = False
    if not valid:
        raise ValueError(name + ' must be a finite number, not a boolean or oversized integer')
    return Fraction(str(value))


def _context(duration_seconds, fps):
    duration = _real(duration_seconds, 'durationSeconds')
    if not 0 < duration <= MAX_DURATION:
        raise ValueError('Capture duration must be positive and at most 600 simulated seconds')
    if type(fps) is not int or not 1 <= fps <= 120:
        raise ValueError('Capture FPS must be an integer between 1 and 120')
    # Source frame budget follows the existing simulator/YAML double formula.
    # Exact-decimal ceiling can invent an extra frame after an IEEE product
    # lands on an integer (e.g. (128/30)*30 == 128.0).
    total = math.ceil(float(duration_seconds) * fps)
    return duration, total


def _half_up(value):
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def _finish(
    mode,
    source,
    request,
    duration,
    fps,
    frame_count,
    requested_times,
    frames,
    *,
    discarded=0,
    rounding='nearest_frame_half_up',
):
    if not frames or len(frames) > MAX_CAPTURES:
        raise ValueError('Capture schedule must contain 1–2000 images')
    if (
        any(type(frame) is not int or not 0 <= frame < frame_count for frame in frames)
        or frames[0] != 0
        or any(a >= b for a, b in zip(frames, frames[1:]))
    ):
        raise ValueError(
            'Capture frames must start at zero and be strictly increasing, unique and inside the simulation'
        )
    effective = [Fraction(frame, fps) for frame in frames]
    maximum = max(abs(a - b) for a, b in zip(requested_times, effective))
    if maximum > Fraction(1, 2 * fps):
        raise ValueError('Capture quantization exceeds half a source frame')
    result = {
        'schema': SCHEMA,
        'mode': mode,
        'source': source,
        'request': copy.deepcopy(request),
        'clock': 'simulated_seconds',
        'endpoint': 'start_inclusive_end_exclusive',
        'fps': fps,
        'durationSeconds': float(duration),
        'simulationFrames': frame_count,
        'count': len(frames),
        'frames': list(frames),
        'requestedTimesSeconds': [float(value) for value in requested_times],
        'effectiveTimesSeconds': [float(value) for value in effective],
        'requestedIntervalSeconds': (
            float(request['intervalSeconds']) if request and mode == 'interval' else None
        ),
        'maxQuantizationErrorSeconds': float(maximum),
        'maxQuantizationErrorFrames': float(maximum * fps),
        'discardedAtOrAfterEndCount': discarded,
        'rounding': rounding,
        'firstCaptureSeconds': float(effective[0]),
        'lastCaptureSeconds': float(effective[-1]),
        'nativeCapturePerformed': False,
    }
    gaps = [b - a for a, b in zip(effective, effective[1:])]
    result['effectiveIntervalSeconds'] = float(gaps[0]) if gaps and len(set(gaps)) == 1 else None
    result['sha256'] = _hash(result)
    return result


def build_schedule(capture, duration_seconds, fps=30):
    """Validate an explicit request and return a pinned endpoint-exclusive plan."""
    duration, total = _context(duration_seconds, fps)
    if not isinstance(capture, dict):
        raise ValueError('capture must be a count or interval request object')
    mode = capture.get('mode')
    requested, frames, discarded = [], [], 0
    if mode == 'count':
        if set(capture) != {'mode', 'count'} or type(capture['count']) is not int:
            raise ValueError('Count capture requires only mode and integer count')
        count = capture['count']
        if not 1 <= count <= min(MAX_CAPTURES, total):
            raise ValueError(
                'Capture count must be 1–2000 and no greater than available source frames'
            )
        times = [duration * index / count for index in range(count)]
        request = {'mode': 'count', 'count': count}
    elif mode == 'interval':
        if set(capture) != {'mode', 'intervalSeconds'}:
            raise ValueError('Interval capture requires only mode and intervalSeconds')
        interval = _real(capture['intervalSeconds'], 'intervalSeconds')
        # Accept the normal JSON floating representation of 1/fps. The exact
        # decimal representation is still used for every absolute instant.
        if capture['intervalSeconds'] < 1 / fps:
            raise ValueError(
                'Capture interval must be at least one source frame (1/FPS simulated seconds)'
            )
        candidates = (
            duration.numerator * interval.denominator
            + duration.denominator * interval.numerator
            - 1
        ) // (duration.denominator * interval.numerator)
        if candidates > MAX_CAPTURES + 1:
            raise ValueError('Interval would generate more than 2000 captures')
        times = [interval * index for index in range(candidates)]
        request = {'mode': 'interval', 'intervalSeconds': capture['intervalSeconds']}
    else:
        raise ValueError('Unknown capture mode; use count or interval')
    for at in times:
        frame = _half_up(at * fps)
        if frame >= total:
            discarded += 1
            continue
        if frames and frame <= frames[-1]:
            raise ValueError(
                'Capture request produces duplicate quantized frames; lower the count or increase the interval'
            )
        frames.append(frame)
        requested.append(at)
    if mode == 'count' and len(frames) != capture['count']:
        raise ValueError(
            'Capture count cannot be represented inside this simulated duration without moving an instant'
        )
    return _finish(
        mode, 'explicit', request, duration, fps, total, requested, frames, discarded=discarded
    )


def legacy_count_schedule(count, duration_seconds, fps=30):
    """Preserve the original campaign-block count placement and ties-to-even."""
    duration, total = _context(duration_seconds, fps)
    if type(count) is not int or not 1 <= count <= min(MAX_CAPTURES, total):
        raise ValueError(
            'Requested images exceed available source frames or the 2000-capture limit'
        )
    targets = (
        [Fraction(0)]
        if count == 1
        else [Fraction(index * (total - 1), count - 1) for index in range(count)]
    )
    # Match the pre-existing floating round(index*(frames-1)/(count-1)).
    frames = [round(float(value)) for value in targets]
    return _finish(
        'count',
        'campaign_block',
        {'mode': 'count', 'count': count},
        duration,
        fps,
        total,
        [value / fps for value in targets],
        frames,
        rounding='legacy_nearest_ties_to_even',
    )


def legacy_frame_schedule(frames, duration_seconds, fps=30):
    duration, total = _context(duration_seconds, fps)
    if not isinstance(frames, list):
        raise ValueError('Legacy capture frames must be an array')
    return _finish(
        'legacy',
        'legacy_planner',
        None,
        duration,
        fps,
        total,
        [Fraction(frame, fps) for frame in frames if type(frame) is int],
        frames,
        rounding='preexisting_frame_schedule',
    )


def validate_plan_schedule(plan, scope):
    """Check immutable copies and recompute their policy; never repair frames."""
    a, b = plan.get('captureSchedule'), scope.get('captureSchedule')
    if a is None and b is None:
        # Historical immutable records remain readable/auditable. Their existing
        # library hashes, not a fabricated new policy, establish provenance.
        frames = plan.get('captureFrames')
        if frames is not None and frames != []:
            legacy_frame_schedule(frames, scope['durationSeconds'], scope['fps'])
        traffic = plan.get('traffic') if isinstance(plan.get('traffic'), dict) else {}
        if traffic.get('captureScheduleVersion'):
            raise ValueError('Pinned capture schedule metadata is missing')
        return None
    if not isinstance(a, dict) or not isinstance(b, dict) or a != b:
        raise ValueError('Plan and scope capture schedule copies do not match')
    if a.get('sha256') != _hash({key: value for key, value in a.items() if key != 'sha256'}):
        raise ValueError('Capture schedule integrity hash was changed')
    if (
        a.get('schema') != SCHEMA
        or a.get('fps') != scope['fps']
        or a.get('durationSeconds') != scope['durationSeconds']
    ):
        raise ValueError('Capture schedule context does not match the simulation')
    frames = plan.get('captureFrames')
    if (
        not isinstance(frames, list)
        or any(type(frame) is not int for frame in frames)
        or frames != a.get('frames')
    ):
        raise ValueError('Capture frames were changed without a matching validated schedule')
    if a.get('source') == 'explicit':
        expected = build_schedule(a.get('request'), scope['durationSeconds'], scope['fps'])
    elif a.get('source') == 'campaign_block':
        expected = legacy_count_schedule(
            a.get('request', {}).get('count'), scope['durationSeconds'], scope['fps']
        )
    elif a.get('source') == 'legacy_planner':
        expected = legacy_frame_schedule(a.get('frames'), scope['durationSeconds'], scope['fps'])
    else:
        raise ValueError('Unknown pinned capture schedule source')
    if expected != a:
        raise ValueError('Capture schedule metadata or integrity hash was changed')
    return expected


def summary(schedule):
    if not isinstance(schedule, dict):
        return {}
    return {
        'plannedCaptureImages': schedule.get('count'),
        'captureMode': schedule.get('mode'),
        'captureIntervalSeconds': schedule.get('requestedIntervalSeconds'),
        'captureDurationSeconds': schedule.get('durationSeconds'),
        'captureLastSeconds': schedule.get('lastCaptureSeconds'),
        'captureClock': 'simulated_seconds',
        'captureScheduleSha256': schedule.get('sha256'),
    }
