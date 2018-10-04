#
# LSST Data Management System
#
# Copyright 2008-2017  AURA/LSST.
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

__all__ = ("MeasureApCorrConfig", "MeasureApCorrTask")

import numpy

import lsst.pex.config
from lsst.afw.image import ApCorrMap
from lsst.afw.math import ChebyshevBoundedField, ChebyshevBoundedFieldConfig
from lsst.pipe.base import Task, Struct
from lsst.meas.base.apCorrRegistry import getApCorrNameSet

from .sourceSelector import sourceSelectorRegistry


class FluxKeys:
    """A collection of keys for a given flux measurement algorithm
    """
    __slots__ = ("flux", "err", "flag", "used")  # prevent accidentally adding fields

    def __init__(self, name, schema):
        """Construct a FluxKeys

        Parameters
        ----------
        name :
            name of flux measurement algorithm, e.g. "base_PsfFlux"
        schema :
            catalog schema containing the flux field
            read: {name}_instFlux, {name}_instFluxErr, {name}_flag
            added: apcorr_{name}_used
        """
        self.flux = schema.find(name + "_instFlux").key
        self.err = schema.find(name + "_instFluxErr").key
        self.flag = schema.find(name + "_flag").key
        self.used = schema.addField("apcorr_" + name + "_used", type="Flag",
                                    doc="set if source was used in measuring aperture correction")

# The following block adds links to these tasks from the Task Documentation page.
## @addtogroup LSST_task_documentation
## @{
## @page measureApCorrTask
## @ref MeasureApCorrTask "MeasureApCorrTask"
##      Task to measure aperture correction
## @}


class MeasureApCorrConfig(lsst.pex.config.Config):
    """Configuration for MeasureApCorrTask
    """
    refFluxName = lsst.pex.config.Field(
        doc="Field name prefix for the flux other measurements should be aperture corrected to match",
        dtype=str,
        default="slot_CalibFlux",
    )
    sourceSelector = sourceSelectorRegistry.makeField(
        doc="Selector that sets the stars that aperture corrections will be measured from.",
        default="flagged",
    )
    minDegreesOfFreedom = lsst.pex.config.RangeField(
        doc="Minimum number of degrees of freedom (# of valid data points - # of parameters);" +
        " if this is exceeded, the order of the fit is decreased (in both dimensions), and" +
        " if we can't decrease it enough, we'll raise ValueError.",
        dtype=int,
        default=1,
        min=1,
    )
    fitConfig = lsst.pex.config.ConfigField(
        doc="Configuration used in fitting the aperture correction fields",
        dtype=ChebyshevBoundedFieldConfig,
    )
    numIter = lsst.pex.config.Field(
        doc="Number of iterations for sigma clipping",
        dtype=int,
        default=4,
    )
    numSigmaClip = lsst.pex.config.Field(
        doc="Number of standard devisations to clip at",
        dtype=float,
        default=3.0,
    )
    allowFailure = lsst.pex.config.ListField(
        doc="Allow these measurement algorithms to fail without an exception",
        dtype=str,
        default=[],
    )

    def validate(self):
        lsst.pex.config.Config.validate(self)
        if self.sourceSelector.target.usesMatches:
            raise lsst.pex.config.FieldValidationError(
                "Star selectors that require matches are not permitted"
            )


class MeasureApCorrTask(Task):
    """This task measures aperture correction for the flux fields returned by
    lsst.meas.base.getApCorrNameSet()

    Notes
    -----
    The main method is @ref MeasureApCorrTask.run "run".

    The lsst.pipe.base.cmdLineTask.CmdLineTask command line task@endlink interface supports a flag
    `--debug` to import `debug.py` from your `$PYTHONPATH`; see @ref baseDebug for more about `debug.py`.

    MeasureApCorrTask has a debug dictionary containing a single boolean key:
    display
    If True: will show plots as aperture corrections are fitted

    Examples
    --------
    For example, put something like the following  into your `debug.py`
    file and run your command-line task with the `--debug` flag (or `import debug`).:
    >>> import lsstDebug
    >>> def DebugInfo(name):
    >>>     di = lsstDebug.getInfo(name)  # N.b. lsstDebug.Info(name) would call us recursively
    >>>     if name == "lsst.meas.algorithms.measureApCorr":
    >>>         di.display = dict(
    >>>             unsubtracted = 1,
    >>>             subtracted = 2,
    >>>             background = 3,)
    >>>
    >>>     return di
    >>>
    >>> lsstDebug.Info = DebugInfo
    >>>
    """
    ConfigClass = MeasureApCorrConfig
    _DefaultName = "measureApCorr"

    def __init__(self, schema, **kwds):
        """Construct a MeasureApCorrTask

        Examples
        --------
        For every name in lsst.meas.base.getApCorrNameSet():
        >>> If the corresponding flux fields exist in the schema:
        >>>     Add a new field apcorr_{name}_used
        >>>     Add an entry to the self.toCorrect dict
        >>> Otherwise silently skip the name
        """
        Task.__init__(self, **kwds)
        self.refFluxKeys = FluxKeys(self.config.refFluxName, schema)
        self.toCorrect = {}  # dict of flux field name prefix: FluxKeys instance
        for name in getApCorrNameSet():
            try:
                self.toCorrect[name] = FluxKeys(name, schema)
            except KeyError:
                # if a field in the registry is missing, just ignore it.
                pass
        self.makeSubtask("sourceSelector")

    def run(self, exposure, catalog):
        """Measure aperture correction

        Parameters
        ----------
        exposure:
            Exposure aperture corrections are being measured
            on. The bounding box is retrieved from it, and
            it is passed to the sourceSelector.
            The output aperture correction map is *not*
            added to the exposure; this is left to the
            caller.

        catalog:
            SourceCatalog containing measurements to be used
            to compute aperturecorrections.

        Returns
        -------
        struct : `an lsst.pipe.base.Struct``

        apCorrMap : `lsst.afw.image.ApCorrMap`
            an aperture correction map () that contains two entries
            for each flux field:
            - ``flux field`` : (e.g. base_PsfFlux_flux): 2d model
            - ``flux sigma`` : field (e.g. base_PsfFlux_fluxErr): 2d model of error
        """
        bbox = exposure.getBBox()
        import lsstDebug
        display = lsstDebug.Info(__name__).display

        self.log.info("Measuring aperture corrections for %d flux fields" % (len(self.toCorrect),))
        # First, create a subset of the catalog that contains only selected stars
        # with non-flagged reference fluxes.
        subset1 = [record for record in self.sourceSelector.run(catalog, exposure=exposure).sourceCat
                   if (not record.get(self.refFluxKeys.flag) and
                       numpy.isfinite(record.get(self.refFluxKeys.flux)))]

        apCorrMap = ApCorrMap()

        # Outer loop over the fields we want to correct
        for name, keys in self.toCorrect.items():
            fluxName = name + "_instFlux"
            fluxErrName = name + "_instFluxErr"

            # Create a more restricted subset with only the objects where the to-be-correct flux
            # is not flagged.
            fluxes = numpy.fromiter((record.get(keys.flux) for record in subset1), float)
            with numpy.errstate(invalid="ignore"):  # suppress NAN warnings
                isGood = numpy.logical_and.reduce([
                    numpy.fromiter((not record.get(keys.flag) for record in subset1), bool),
                    numpy.isfinite(fluxes),
                    fluxes > 0.0,
                ])
            subset2 = [record for record, good in zip(subset1, isGood) if good]

            # Check that we have enough data points that we have at least the minimum of degrees of
            # freedom specified in the config.
            if len(subset2) - 1 < self.config.minDegreesOfFreedom:
                if name in self.config.allowFailure:
                    self.log.warn("Unable to measure aperture correction for '%s': "
                                  "only %d sources, but require at least %d." %
                                  (name, len(subset2), self.config.minDegreesOfFreedom+1))
                    continue
                raise RuntimeError("Unable to measure aperture correction for required algorithm '%s': "
                                   "only %d sources, but require at least %d." %
                                   (name, len(subset2), self.config.minDegreesOfFreedom+1))

            # If we don't have enough data points to constrain the fit, reduce the order until we do
            ctrl = self.config.fitConfig.makeControl()
            while len(subset2) - ctrl.computeSize() < self.config.minDegreesOfFreedom:
                if ctrl.orderX > 0:
                    ctrl.orderX -= 1
                if ctrl.orderY > 0:
                    ctrl.orderY -= 1

            # Fill numpy arrays with positions and the ratio of the reference flux to the to-correct flux
            x = numpy.zeros(len(subset2), dtype=float)
            y = numpy.zeros(len(subset2), dtype=float)
            apCorrData = numpy.zeros(len(subset2), dtype=float)
            indices = numpy.arange(len(subset2), dtype=int)
            for n, record in enumerate(subset2):
                x[n] = record.getX()
                y[n] = record.getY()
                apCorrData[n] = record.get(self.refFluxKeys.flux)/record.get(keys.flux)

            for _i in range(self.config.numIter):

                # Do the fit, save it in the output map
                apCorrField = ChebyshevBoundedField.fit(bbox, x, y, apCorrData, ctrl)

                if display:
                    plotApCorr(bbox, x, y, apCorrData, apCorrField, "%s, iteration %d" % (name, _i))

                # Compute errors empirically, using the RMS difference between the true reference flux and the
                # corrected to-be-corrected flux.
                apCorrDiffs = apCorrField.evaluate(x, y)
                apCorrDiffs -= apCorrData
                apCorrErr = numpy.mean(apCorrDiffs**2)**0.5

                # Clip bad data points
                apCorrDiffLim = self.config.numSigmaClip * apCorrErr
                with numpy.errstate(invalid="ignore"):  # suppress NAN warning
                    keep = numpy.fabs(apCorrDiffs) <= apCorrDiffLim
                x = x[keep]
                y = y[keep]
                apCorrData = apCorrData[keep]
                indices = indices[keep]

            # Final fit after clipping
            apCorrField = ChebyshevBoundedField.fit(bbox, x, y, apCorrData, ctrl)

            self.log.info("Aperture correction for %s: RMS %f from %d" %
                          (name, numpy.mean((apCorrField.evaluate(x, y) - apCorrData)**2)**0.5, len(indices)))

            if display:
                plotApCorr(bbox, x, y, apCorrData, apCorrField, "%s, final" % (name,))

            # Save the result in the output map
            # The error is constant spatially (we could imagine being
            # more clever, but we're not yet sure if it's worth the effort).
            # We save the errors as a 0th-order ChebyshevBoundedField
            apCorrMap[fluxName] = apCorrField
            apCorrErrCoefficients = numpy.array([[apCorrErr]], dtype=float)
            apCorrMap[fluxErrName] = ChebyshevBoundedField(bbox, apCorrErrCoefficients)

            # Record which sources were used
            for i in indices:
                subset2[i].set(keys.used, True)

        return Struct(
            apCorrMap=apCorrMap,
        )


def plotApCorr(bbox, xx, yy, zzMeasure, field, title):
    """Plot aperture correction fit residuals. There are two subplots: residuals against x and y.
    Intended for debugging.

    Parameters
    ----------
    bbox:
        Bounding box (for bounds)
    xx:
        x coordinates
    yy:
        y coordinates
    zzMeasure:
        Measured value of the aperture correction
    field:
        Fit aperture correction field
    title:
        Title for plot
    """
    import matplotlib.pyplot as plt

    zzFit = field.evaluate(xx, yy)
    residuals = zzMeasure - zzFit

    fig, axes = plt.subplots(2, 1)

    axes[0].scatter(xx, residuals, s=2, marker='o', lw=0, alpha=0.3)
    axes[1].scatter(yy, residuals, s=2, marker='o', lw=0, alpha=0.3)
    for ax in axes:
        ax.set_ylabel("Residual")
        ax.set_ylim(0.9*residuals.min(), 1.1*residuals.max())
    axes[0].set_xlabel("x")
    axes[0].set_xlim(bbox.getMinX(), bbox.getMaxX())
    axes[1].set_xlabel("y")
    axes[1].set_xlim(bbox.getMinY(), bbox.getMaxY())
    plt.suptitle(title)

    plt.show()
