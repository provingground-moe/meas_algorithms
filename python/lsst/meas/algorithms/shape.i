// -*- lsst-c++ -*-

%{
#   include "lsst/meas/algorithms/Shape.h"
%}

%include "lsst/meas/algorithms/Shape.h"

%template(measureShapeF) lsst::meas::algorithms::measureShape<lsst::afw::image::Image<float> >;
%template(createMeasureShape) lsst::meas::algorithms::createMeasureShape<lsst::afw::image::Image<float> >;