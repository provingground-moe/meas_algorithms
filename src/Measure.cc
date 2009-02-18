/// \file

#include "lsst/pex/exceptions.h"
#include "lsst/pex/logging/Trace.h"
#include "lsst/meas/algorithms/Measure.h"
#include "lsst/meas/algorithms/Centroid.h"

namespace lsst { namespace meas { namespace algorithms {
namespace image = lsst::afw::image;
namespace detection = lsst::afw::detection;

/************************************************************************************************************/
/**
 * \brief Calculate a detected source's moments
 */
template <typename MaskedImageT>
class FootprintCentroid : public detection::FootprintFunctor<MaskedImageT> {
public:
    FootprintCentroid(MaskedImageT const& mimage                    ///< The image the source lives in
                     ) : detection::FootprintFunctor<MaskedImageT>(mimage),
                         _n(0), _sum(0), _sumx(0), _sumy(0),
                         _max(-std::numeric_limits<double>::max()), _xmax(0), _ymax(0)
        {}

    /// \brief method called for each pixel by apply()
    void operator()(typename MaskedImageT::xy_locator loc, ///< locator pointing at the pixel
                    int x,                                 ///< column-position of pixel
                    int y                                  ///< row-position of pixel
                   ) {
        typename MaskedImageT::Image::Pixel val = loc.image(0, 0);

        _n++;
        _sum += val;
        _sumx += lsst::afw::image::indexToPosition(x)*val;
        _sumy += lsst::afw::image::indexToPosition(y)*val;

        if (val > _max) {
            _max = val;
            _xmax = x;
            _ymax = y;
        }
    }

    /// Return the number of pixels
    int getN() const { return _n; }
    /// Return the Footprint's flux
    double getSum() const { return _sum; }
    /// Return the Footprint's column centroid
    double getX() const { return _sumx/_sum; }
    /// Return the Footprint's row centroid
    double getY() const { return _sumy/_sum; }
    /// Return the Footprint's peak pixel
    detection::Peak getPeak() const { return detection::Peak(_xmax, _ymax); }
private:
    int _n;
    double _sum, _sumx, _sumy;
    double _max;
    int _xmax, _ymax;
};

/************************************************************************************************************/
/**
 * \brief Set some fields in a Source from foot (which was found in mimage)
 */
template<typename MaskedImageT>
void measureSource(lsst::afw::detection::Source::Ptr src, ///< the Source to receive results
                   MaskedImageT& mimage,                  ///< image wherein Footprint dwells
                   lsst::afw::detection::Footprint const& foot, ///< Footprint to measure
                   lsst::pex::policy::Policy const& policy,     ///< Policy to describe processing
                   float background,                            ///< background level to subtract
                   PSF const* psf                               ///< mimage's PSF \todo Cf #645
                  ) {
    //
    // Measure some properties of the Footprint
    //
    FootprintCentroid<MaskedImageT> centroidFunctor(mimage);
    centroidFunctor.apply(foot);

    detection::Peak const& peak = centroidFunctor.getPeak();
    src->setPsfMag(centroidFunctor.getSum());  // this isn't a magnitude!
    //
    // Now run measure objects code
    //
    std::string const& centroidAlgorithm = policy.getString("measureObjects.centroidAlgorithm"); // algorithm to use
   
    typename MaskedImageT::Mask &mask = *mimage.getMask();
    if (mask(peak.getIx() - mask.getX0(), peak.getIy() - mask.getY0(), MaskedImageT::Mask::getMaskPlane("EDGE"))) {
        src->setFlagForDetection(src->getFlagForDetection() | Flags::EDGE);
        return;
    }

    measureCentroid<typename MaskedImageT::Image> *mc =
        createMeasureCentroid<typename MaskedImageT::Image>(centroidAlgorithm);

    try {
        Centroid cen = mc->apply(*mimage.getImage(), peak.getIx(), peak.getIy(), psf, background);
        
        src->setXAstrom(cen.getX());
        src->setYAstrom(cen.getY());
    } catch (lsst::pex::exceptions::RuntimeErrorException const& e) {
        src->setXAstrom(peak.getIx());
        src->setYAstrom(peak.getIy());
        src->setFlagForDetection(src->getFlagForDetection() | Flags::PEAKCENTER);

        return;
    }
}

//
// Explicit instantiations
//
// \cond
template void measureSource(detection::Source::Ptr src, image::MaskedImage<float>& mimage,
                            detection::Footprint const &foot,
                            lsst::pex::policy::Policy const& policy,
                            float background, PSF const*psf);
// \endcond
}}}