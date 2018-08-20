#
# LSST Data Management System
#
# Copyright 2008-2016  AURA/LSST.
#
# This product includes software developed by the
# LSST Project (http://www.lsst.org/).
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the LSST License Statement and
# the GNU General Public License along with this program.  If not,
# see <https://www.lsstcorp.org/LegalNotices/>.
#
import os
import unittest
import math

import lsst.geom
import lsst.afw.detection as afwDetection
import lsst.afw.image as afwImage
import lsst.afw.math as afwMath
import lsst.afw.table as afwTable
from lsst.log import Log
import lsst.meas.base as measBase
import lsst.meas.algorithms as algorithms
import lsst.meas.algorithms.defects as defects
import lsst.pex.config as pexConfig
import lsst.utils.tests

# Change the level to Log.DEBUG or Log.TRACE to see debug messages
Log.getLogger("measurement").setLevel(Log.INFO)

try:
    type(display)
except NameError:
    display = False
else:
    import lsst.afw.display as afwDisplay
    afwDisplay.setDefaultMaskTransparency(75)

# Determine if we have afwdata
try:
    afwdataDir = lsst.utils.getPackageDir('afwdata')
except Exception:
    afwdataDir = None


def toString(*args):
    """toString written in python"""
    if len(args) == 1:
        args = args[0]

    y, x0, x1 = args
    return "%d: %d..%d" % (y, x0, x1)


class MeasureTestCase(lsst.utils.tests.TestCase):
    """A test case for Measure"""
    class Object:

        def __init__(self, val, spans):
            self.val = val
            self.spans = spans

        def insert(self, im, dx=0, dy=0):
            """Insert self into an image"""
            for sp in self.spans:
                y, x0, x1 = sp
                for x in range(x0, x1 + 1):
                    im[x + dx, y + dy, afwImage.LOCAL] = self.val

        def __eq__(self, other):
            for osp, sp in zip(other.getSpans(), self.spans):
                if osp.toString() != toString(sp):
                    return False

            return True

    def setUp(self):
        ms = afwImage.MaskedImageF(lsst.geom.ExtentI(31, 27))
        ms.getVariance().set(1)
        bbox = lsst.geom.BoxI(lsst.geom.PointI(1, 1), lsst.geom.ExtentI(24, 20))
        self.mi = afwImage.MaskedImageF(ms, bbox, afwImage.LOCAL)
        self.exposure = afwImage.makeExposure(self.mi)
        im = self.mi.getImage()
        #
        # Objects that we should detect.  These are coordinates in the subimage
        #
        self.objects = []
        self.objects += [self.Object(10, [(1, 4, 4), (2, 3, 5), (3, 4, 4)])]
        self.objects += [self.Object(20, [(5, 7, 8), (5, 10, 10), (6, 8, 9)])]
        self.objects += [self.Object(20, [(8, 3, 3)])]

        im.set(0)                       # clear image
        for obj in self.objects:
            obj.insert(im, 5, 5)
        #
        # Add a few more pixels to make peaks that we can centroid around
        #
        for x, y in [(9, 7), (13, 11)]:
            im[x, y, afwImage.LOCAL] += 1

    def tearDown(self):
        del self.mi
        del self.exposure

    def testFootprintsMeasure(self):
        """Check that we can measure the objects in a detectionSet"""

        xcentroid = [10.0, 14.0, 9.0]
        ycentroid = [8.0, 11.5061728, 14.0]
        flux = [51.0, 101.0, 20.0]
        # sqrt of num pixels in aperture; note the second source is offset
        # from the pixel grid.
        fluxErr = [math.sqrt(29), math.sqrt(27), math.sqrt(29)]

        footprints = afwDetection.FootprintSet(self.mi, afwDetection.Threshold(10), "DETECTED")

        if display:
            disp = afwDisplay.Display(frame=0)
            disp.mtv(self.mi, title=self._testMethodName + ": image")
            afwDisplay.Display(frame=1).mtv(self.mi.getVariance(), title=self._testMethodName + ": variance")

        measureSourcesConfig = measBase.SingleFrameMeasurementConfig()
        measureSourcesConfig.algorithms["base_CircularApertureFlux"].radii = [3.0]
        # Numerical tests below assumes that we are not using sinc fluxes.
        measureSourcesConfig.algorithms["base_CircularApertureFlux"].maxSincRadius = 0.0
        measureSourcesConfig.algorithms.names = ["base_NaiveCentroid", "base_SdssShape", "base_PsfFlux",
                                                 "base_CircularApertureFlux"]
        measureSourcesConfig.slots.centroid = "base_NaiveCentroid"
        measureSourcesConfig.slots.psfFlux = "base_PsfFlux"
        measureSourcesConfig.slots.apFlux = "base_CircularApertureFlux_3_0"
        measureSourcesConfig.slots.modelFlux = None
        measureSourcesConfig.slots.gaussianFlux = None
        measureSourcesConfig.slots.calibFlux = None

        schema = afwTable.SourceTable.makeMinimalSchema()
        task = measBase.SingleFrameMeasurementTask(schema, config=measureSourcesConfig)
        measCat = afwTable.SourceCatalog(schema)
        footprints.makeSources(measCat)
        # now run the SFM task with the test plugin
        sigma = 1e-10
        psf = algorithms.DoubleGaussianPsf(11, 11, sigma)  # i.e. a single pixel
        self.exposure.setPsf(psf)
        task.run(measCat, self.exposure)

        self.assertEqual(len(measCat), len(flux))
        for i, source in enumerate(measCat):

            xc, yc = source.getX(), source.getY()
            if display:
                disp.dot("+", xc, yc)

            self.assertAlmostEqual(source.getX(), xcentroid[i], 6)
            self.assertAlmostEqual(source.getY(), ycentroid[i], 6)
            self.assertEqual(source.getApInstFlux(), flux[i])
            self.assertAlmostEqual(source.getApInstFluxErr(), fluxErr[i], 6)

            # We're using a delta-function PSF, so the psfFlux should be the
            # pixel under the centroid, iff the object's centred in the pixel
            if xc == int(xc) and yc == int(yc):
                self.assertAlmostEqual(source.getPsfInstFlux(),
                                       self.exposure.getMaskedImage().getImage()[int(xc + 0.5),
                                                                                 int(yc + 0.5)])
                self.assertAlmostEqual(source.getPsfInstFluxErr(),
                                       self.exposure.getMaskedImage().getVariance()[int(xc + 0.5),
                                                                                    int(yc + 0.5)])


class FindAndMeasureTestCase(lsst.utils.tests.TestCase):
    """A test case detecting and measuring objects."""

    def setUp(self):
        self.mi = afwImage.MaskedImageF(os.path.join(afwdataDir,
                                                     "CFHT", "D4", "cal-53535-i-797722_1.fits"))

        self.FWHM = 5
        self.psf = algorithms.DoubleGaussianPsf(15, 15, self.FWHM/(2*math.sqrt(2*math.log(2))))

        if False:                       # use full image, trimmed to data section
            self.XY0 = lsst.geom.PointI(32, 2)
            self.mi = self.mi.Factory(self.mi, lsst.geom.BoxI(self.XY0, lsst.geom.PointI(2079, 4609)),
                                      afwImage.LOCAL)
            self.mi.setXY0(lsst.geom.PointI(0, 0))
        else:                           # use sub-image
            self.XY0 = lsst.geom.PointI(824, 140)
            self.mi = self.mi.Factory(self.mi, lsst.geom.BoxI(self.XY0, lsst.geom.ExtentI(256, 256)),
                                      afwImage.LOCAL)

        self.mi.getMask().addMaskPlane("DETECTED")
        self.exposure = afwImage.makeExposure(self.mi)

    def tearDown(self):
        del self.mi
        del self.psf
        del self.exposure

    @unittest.skipUnless(afwdataDir, "afwdata not available")
    def testDetection(self):
        """Test object detection"""
        #
        # Fix defects
        #
        # Mask known bad pixels
        #
        measAlgorithmsDir = lsst.utils.getPackageDir('meas_algorithms')
        badPixels = defects.policyToBadRegionList(os.path.join(measAlgorithmsDir,
                                                               "policy/BadPixels.paf"))
        # did someone lie about the origin of the maskedImage?  If so, adjust bad pixel list
        if self.XY0.getX() != self.mi.getX0() or self.XY0.getY() != self.mi.getY0():
            dx = self.XY0.getX() - self.mi.getX0()
            dy = self.XY0.getY() - self.mi.getY0()
            for bp in badPixels:
                bp.shift(-dx, -dy)

        algorithms.interpolateOverDefects(self.mi, self.psf, badPixels)
        #
        # Subtract background
        #
        bgGridSize = 64  # was 256 ... but that gives only one region and the spline breaks
        bctrl = afwMath.BackgroundControl(afwMath.Interpolate.NATURAL_SPLINE)
        bctrl.setNxSample(int(self.mi.getWidth()/bgGridSize) + 1)
        bctrl.setNySample(int(self.mi.getHeight()/bgGridSize) + 1)
        backobj = afwMath.makeBackground(self.mi.getImage(), bctrl)

        self.mi.getImage()[:] -= backobj.getImageF()
        #
        # Remove CRs
        #
        crConfig = algorithms.FindCosmicRaysConfig()
        algorithms.findCosmicRays(self.mi, self.psf, 0, pexConfig.makePolicy(crConfig))
        #
        # We do a pretty good job of interpolating, so don't propagagate the convolved CR/INTRP bits
        # (we'll keep them for the original CR/INTRP pixels)
        #
        savedMask = self.mi.getMask().Factory(self.mi.getMask(), True)
        saveBits = savedMask.getPlaneBitMask("CR") | \
            savedMask.getPlaneBitMask("BAD") | \
            savedMask.getPlaneBitMask("INTRP")  # Bits to not convolve
        savedMask &= saveBits

        msk = self.mi.getMask()
        msk &= ~saveBits  # Clear the saved bits
        del msk
        #
        # Smooth image
        #
        psf = algorithms.DoubleGaussianPsf(15, 15, self.FWHM/(2*math.sqrt(2*math.log(2))))

        cnvImage = self.mi.Factory(self.mi.getBBox())
        kernel = psf.getKernel()
        afwMath.convolve(cnvImage, self.mi, kernel, afwMath.ConvolutionControl())

        msk = cnvImage.getMask()
        msk |= savedMask  # restore the saved bits
        del msk

        threshold = afwDetection.Threshold(3, afwDetection.Threshold.STDEV)
        #
        # Only search the part of the frame that was PSF-smoothed
        #
        llc = lsst.geom.PointI(psf.getKernel().getWidth()//2, psf.getKernel().getHeight()//2)
        urc = lsst.geom.PointI(cnvImage.getWidth() - llc[0] - 1, cnvImage.getHeight() - llc[1] - 1)
        middle = cnvImage.Factory(cnvImage, lsst.geom.BoxI(llc, urc), afwImage.LOCAL)
        ds = afwDetection.FootprintSet(middle, threshold, "DETECTED")
        del middle
        #
        # Reinstate the saved (e.g. BAD) (and also the DETECTED | EDGE) bits in the unsmoothed image
        #
        savedMask[:] = cnvImage.getMask()
        msk = self.mi.getMask()
        msk |= savedMask
        del msk
        del savedMask

        if display:
            disp = afwDisplay.Display(frame=2)
            disp.mtv(self.mi, title=self._testMethodName + ": image")
            afwDisplay.Display(frame=3).mtv(cnvImage, title=self._testMethodName + ": cnvImage")

        #
        # Time to actually measure
        #
        schema = afwTable.SourceTable.makeMinimalSchema()
        sfm_config = measBase.SingleFrameMeasurementConfig()
        sfm_config.plugins = ["base_SdssCentroid", "base_CircularApertureFlux", "base_PsfFlux",
                              "base_SdssShape", "base_GaussianFlux",
                              "base_PixelFlags"]
        sfm_config.slots.centroid = "base_SdssCentroid"
        sfm_config.slots.shape = "base_SdssShape"
        sfm_config.slots.psfFlux = "base_PsfFlux"
        sfm_config.slots.gaussianFlux = None
        sfm_config.slots.apFlux = "base_CircularApertureFlux_3_0"
        sfm_config.slots.modelFlux = "base_GaussianFlux"
        sfm_config.slots.calibFlux = None
        sfm_config.plugins["base_SdssShape"].maxShift = 10.0
        sfm_config.plugins["base_CircularApertureFlux"].radii = [3.0]
        task = measBase.SingleFrameMeasurementTask(schema, config=sfm_config)
        measCat = afwTable.SourceCatalog(schema)
        # detect the sources and run with the measurement task
        ds.makeSources(measCat)
        self.exposure.setPsf(self.psf)
        task.run(measCat, self.exposure)

        self.assertGreater(len(measCat), 0)
        for source in measCat:
            if source.get("base_PixelFlags_flag_edge"):
                continue

            if display:
                disp.dot("+", source.getX(), source.getY())


class GaussianPsfTestCase(lsst.utils.tests.TestCase):
    """A test case detecting and measuring Gaussian PSFs."""

    def setUp(self):
        FWHM = 5
        psf = algorithms.DoubleGaussianPsf(15, 15, FWHM/(2*math.sqrt(2*math.log(2))))
        mi = afwImage.MaskedImageF(lsst.geom.ExtentI(100, 100))

        self.xc, self.yc, self.instFlux = 45, 55, 1000.0
        mi.image[self.xc, self.yc, afwImage.LOCAL] = self.instFlux

        cnvImage = mi.Factory(mi.getDimensions())
        afwMath.convolve(cnvImage, mi, psf.getKernel(), afwMath.ConvolutionControl())

        self.exp = afwImage.makeExposure(cnvImage)
        self.exp.setPsf(psf)

        if display and False:
            afwDisplay.Display(frame=0).mtv(self.exp, title=self._testMethodName + ": image")

    def tearDown(self):
        del self.exp

    def testPsfFlux(self):
        """Test that fluxes are measured correctly."""
        #
        # Total flux in image
        #
        flux = afwMath.makeStatistics(self.exp.getMaskedImage(), afwMath.SUM).getValue()
        self.assertAlmostEqual(flux/self.instFlux, 1.0)

        #
        # Various algorithms
        #
        rad = 10.0

        schema = afwTable.SourceTable.makeMinimalSchema()
        schema.addField("centroid_x", type=float)
        schema.addField("centroid_y", type=float)
        schema.addField("centroid_flag", type='Flag')
        sfm_config = measBase.SingleFrameMeasurementConfig()
        sfm_config.doReplaceWithNoise = False
        sfm_config.plugins = ["base_CircularApertureFlux", "base_PsfFlux"]
        sfm_config.slots.centroid = "centroid"
        sfm_config.slots.shape = None
        sfm_config.slots.psfFlux = None
        sfm_config.slots.gaussianFlux = None
        sfm_config.slots.apFlux = None
        sfm_config.slots.modelFlux = None
        sfm_config.slots.calibFlux = None
        sfm_config.plugins["base_SdssShape"].maxShift = 10.0
        sfm_config.plugins["base_CircularApertureFlux"].radii = [rad]
        task = measBase.SingleFrameMeasurementTask(schema, config=sfm_config)
        measCat = afwTable.SourceCatalog(schema)
        source = measCat.addNew()
        source.set("centroid_x", self.xc)
        source.set("centroid_y", self.yc)
        task.run(measCat, self.exp)
        for algName in ["base_CircularApertureFlux_10_0", "base_PsfFlux"]:
            instFlux = source.get(algName + "_instFlux")
            flag = source.get(algName + "_flag")
            self.assertEqual(flag, False)
            self.assertAlmostEqual(instFlux/self.instFlux, 1.0, 4, "Measuring with %s: %g v. %g" %
                                   (algName, instFlux, self.instFlux))


class TestMemory(lsst.utils.tests.MemoryTestCase):
    pass


def setup_module(module):
    lsst.utils.tests.init()


if __name__ == "__main__":
    lsst.utils.tests.init()
    unittest.main()
