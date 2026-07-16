from qgis.core import (QgsProcessingAlgorithm, 
                       QgsProcessingParameterMultipleLayers, 
                       QgsProcessingParameterRasterDestination,
                       QgsProcessing)
import numpy as np
from osgeo import gdal

class RobustSentinelMedianEN(QgsProcessingAlgorithm):
    INPUT_RASTERS = 'INPUT_RASTERS'
    OUTPUT_RASTER = 'OUTPUT_RASTER'

    def tr(self, string):
        return string

    def createInstance(self):
        return RobustSentinelMedianEN()

    def name(self):
        return 'robust_sentinel_median_en'

    def displayName(self):
        return self.tr('Robust Multi-Band Sentinel-2 Median')

    def group(self):
        return self.tr('Custom Raster Analysis')

    def groupId(self):
        return 'custom_raster_analysis'

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterMultipleLayers(
                self.INPUT_RASTERS,
                self.tr('Input multi-band rasters (variable count)'),
                layerType=QgsProcessing.TypeRaster
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUTPUT_RASTER,
                self.tr('Output merged median raster')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        layers = self.parameterAsLayerList(parameters, self.INPUT_RASTERS, context)
        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT_RASTER, context)

        if not layers:
            return {}

        filepaths = [layer.source() for layer in layers]
        
        # Step 1: Find the minimum common dimensions across all files (safe intersection)
        min_cols = None
        min_rows = None
        bands = None
        
        for path in filepaths:
            ds = gdal.Open(path)
            if ds is None:
                continue
            if min_cols is None or ds.RasterXSize < min_cols:
                min_cols = ds.RasterXSize
            if min_rows is None or ds.RasterYSize < min_rows:
                min_rows = ds.RasterYSize
            if bands is None:
                bands = ds.RasterCount
                
        # Get reference geometry from the first raster
        ds_ref = gdal.Open(filepaths[0])
        geo_transform = ds_ref.GetGeoTransform()
        projection = ds_ref.GetProjection()

        # Prepare output dataset with safe minimum common dimensions
        driver = gdal.GetDriverByName('GTiff')
        out_ds = driver.Create(output_path, min_cols, min_rows, bands, gdal.GDT_Float32)
        out_ds.SetGeoTransform(geo_transform)
        out_ds.SetProjection(projection)

        # Step 2: Iterate through spectral bands
        for b in range(1, bands + 1):
            feedback.setProgress(int((b - 1) / bands * 100))
            if feedback.isCanceled():
                break
                
            stack = np.zeros((len(filepaths), min_rows, min_cols), dtype=np.float32)
            nodata_value = None

            for idx, path in enumerate(filepaths):
                ds = gdal.Open(path)
                band = ds.GetRasterBand(b)
                nodata_value = band.GetNoDataValue()
                
                # Safe read using the computed minimum common window size
                arr = band.ReadAsArray(0, 0, min_cols, min_rows).astype(np.float32)
                
                if nodata_value is not None:
                    arr[arr == nodata_value] = np.nan
                stack[idx, :, :] = arr

            # Calculate pixel median along the time/stack axis
            median_array = np.nanmedian(stack, axis=0)

            # Write data to the output band
            out_band = out_ds.GetRasterBand(b)
            out_band.WriteArray(median_array)
            if nodata_value is not None:
                out_band.SetNoDataValue(nodata_value)
            out_band.FlushCache()

        del out_ds, ds_ref
        return {self.OUTPUT_RASTER: output_path}