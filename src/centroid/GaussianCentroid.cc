// -*- LSST-C++ -*-
/**
 * @file
 */
#include "lsst/pex/exceptions.h"
#include "lsst/pex/logging/Trace.h"
#include "lsst/afw/image.h"
#include "lsst/afw/detection/Psf.h"
#include "lsst/meas/algorithms/Measure.h"
#include "all.h"

namespace pexExceptions = lsst::pex::exceptions;
namespace pexLogging = lsst::pex::logging;
namespace afwDetection = lsst::afw::detection;
namespace afwImage = lsst::afw::image;

namespace lsst {
namespace meas {
namespace algorithms {

namespace {

/**
 * @brief A class that knows how to calculate centroids as a simple unweighted first moment
 * of the 3x3 region around a pixel
 */
class GaussianAstrometry : public afwDetection::Astrometry
{
public:
    typedef boost::shared_ptr<GaussianAstrometry> Ptr;
    typedef boost::shared_ptr<GaussianAstrometry const> ConstPtr;

    /// Ctor
    GaussianAstrometry(double x, double xErr, double y, double yErr)
    {
        init();                         // This allocates space for fields added by defineSchema
        set<X>(x);                      // ... if you don't, these set calls will fail an assertion
        set<X_ERR>(xErr);               // the type of the value must match the schema
        set<Y>(y);
        set<Y_ERR>(yErr);
    }

    /// Add desired fields to the schema
    virtual void defineSchema(afwDetection::Schema::Ptr schema ///< our schema; == _mySchema
                     ) {
        Astrometry::defineSchema(schema);
    }

    template<typename MaskedImageT>
    static Astrometry::Ptr doMeasure(typename MaskedImageT::ConstPtr im, afwDetection::Peak const&);
};

/**
 * @brief Given an image and a pixel position, calculate a position using a Gaussian fit
 */
template<typename MaskedImageT>
afwDetection::Astrometry::Ptr GaussianAstrometry::doMeasure(typename MaskedImageT::ConstPtr image,
                                                            afwDetection::Peak const& peak)
{
    int x = static_cast<int>(peak.getIx() + 0.5);
    int y = static_cast<int>(peak.getIy() + 0.5);

    x -= image->getX0();                 // work in image Pixel coordinates
    y -= image->getY0();

    FittedModel fit = twodg(*image->getImage(), x, y); // here's the fitter

    if (fit.params[FittedModel::PEAK] <= 0) {
        throw LSST_EXCEPT(pexExceptions::RuntimeErrorException,
                          (boost::format("Object at (%d, %d) has a peak of %g") %
                           x % y % fit.params[FittedModel::PEAK]).str());
    }

    double const posErr = std::numeric_limits<double>::quiet_NaN();
    
    return boost::make_shared<GaussianAstrometry>(
        lsst::afw::image::indexToPosition(image->getX0()) + fit.params[FittedModel::X0], posErr,
        lsst::afw::image::indexToPosition(image->getY0()) + fit.params[FittedModel::Y0], posErr);
}

/*
 * Declare the existence of a "GAUSSIAN" algorithm to MeasureAstrometry
 *
 * \cond
 */
#define INSTANTIATE(TYPE) \
    MeasureAstrometry<afwImage::MaskedImage<TYPE> >::declare("GAUSSIAN", \
        &GaussianAstrometry::doMeasure<afwImage::MaskedImage<TYPE> > \
        )

volatile bool isInstance[] = {
    INSTANTIATE(int),
    INSTANTIATE(float)
};

// \endcond

}}}}
