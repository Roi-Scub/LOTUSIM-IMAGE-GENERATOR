#if UNITY_INCLUDE_TESTS
using System;
using System.IO;
using NUnit.Framework;
using Lotusim.EditorTools;

namespace Lotusim.EditorTests
{
    // Compiled with the Editor test assembly. Execution requires explicit Unity
    // test-runner consent; compiling these is not a rendered-image validation.
    public sealed class DatasetTrafficLibraryTests
    {
        [Test]
        public void PinnedTwoSecondCadenceIsValid()
        {
            DatasetTrafficLibraryImportContract.ValidateFrames(new[] { 0, 60, 120, 180, 240 }, 30, 10);
        }

        [Test]
        public void EmptyDuplicateUnsortedAndEndBoundaryAreRefused()
        {
            foreach (var frames in new[]
            {
                new int[0],
                new[]
                {
                    0,
                    60,
                    60
                },
                new[]
                {
                    60,
                    0
                },
                new[]
                {
                    -1
                },
                new[]
                {
                    300
                }
            }

            )
                Assert.Throws<InvalidDataException>(() => DatasetTrafficLibraryImportContract.ValidateFrames(frames, 30, 10));
        }

        [Test]
        public void ImageBudgetIsBounded()
        {
            Assert.Throws<InvalidDataException>(() => DatasetTrafficLibraryImportContract.ValidateFrames(new int[2001], 30, 600));
            Assert.Throws<InvalidDataException>(() => DatasetTrafficLibraryImportContract.ValidateFrames(new[] { 0 }, 0, 10));
        }

        [Test]
        public void LibraryIdAndHashesAreOpaque()
        {
            Assert.IsTrue(DatasetTrafficLibraryImportContract.Id("12345678-1234-4234-8234-123456789abc"));
            Assert.IsFalse(DatasetTrafficLibraryImportContract.Id("../../secret"));
            Assert.IsFalse(DatasetTrafficLibraryImportContract.Id("12345678-1234-1234-1234-123456789abc"));
            Assert.IsFalse(DatasetTrafficLibraryImportContract.Hex(new string ('x', 64), 64));
        }
    }
}
#endif
