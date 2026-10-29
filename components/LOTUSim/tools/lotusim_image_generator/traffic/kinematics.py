"""Pure route equations shared by planning and editing. Unity axes: X east, Y up, Z north.

No storage, UI, telemetry or engine dependency. Values are metres and seconds.
"""

import math

KNOT = 1852 / 3600


def vec(v):
    return {'x': v[0], 'y': v[1], 'z': v[2]}


def arr(v):
    return [v[k] for k in ('x', 'y', 'z')]


def plus(a, b):
    return [x + y for x, y in zip(a, b)]


def minus(a, b):
    return [x - y for x, y in zip(a, b)]


def times(a, t):
    return [x * t for x in a]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def norm(a):
    return math.sqrt(dot(a, a))


def bearing(degrees):
    a = math.radians(degrees)
    return [math.sin(a), 0, math.cos(a)]


def mps(value, unit):
    if unit not in ('kn', 'kmh', 'mps'):
        raise ValueError('Explicit speed unit must be kn, kmh or mps')
    return value * {'kn': KNOT, 'kmh': 1 / 3.6, 'mps': 1}[unit]


def finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def interval(pair, low, high):
    return (
        isinstance(pair, list)
        and len(pair) == 2
        and all(finite(v) for v in pair)
        and low <= pair[0] <= pair[1] <= high
    )


def turn_time(route, t):
    return (
        max(route['turnStartSeconds'], min(route['turnEndSeconds'], t))
        if route.get('boundedTurn')
        else t
    )


def velocity_at(route, t):
    v = route['velocity']
    a = math.radians(route.get('yawRateDegS', 0)) * (turn_time(route, t) - route['focus'])
    return [math.cos(a) * v[0] + math.sin(a) * v[2], v[1], -math.sin(a) * v[0] + math.cos(a) * v[2]]


def position(route, t):
    v = route['velocity']
    w = math.radians(route.get('yawRateDegS', 0))
    dt = t - route['focus']
    if abs(w) < 1e-9:
        return plus(route['center'], times(v, dt))
    q = turn_time(route, t) - route['focus']
    a = w * q
    delta = [
        (v[0] * math.sin(a) + v[2] * (1 - math.cos(a))) / w,
        v[1] * dt,
        (v[0] * (math.cos(a) - 1) + v[2] * math.sin(a)) / w,
    ]
    if route.get('boundedTurn'):
        for at, extra in [
            (route['turnStartSeconds'], min(0, t - route['turnStartSeconds'])),
            (route['turnEndSeconds'], max(0, t - route['turnEndSeconds'])),
        ]:
            extra_velocity = velocity_at(route, at)
            extra_velocity[1] = 0
            delta = plus(delta, times(extra_velocity, extra))
    return plus(route['center'], delta)
