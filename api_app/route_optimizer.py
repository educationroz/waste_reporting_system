import math

from api_app.models import Bin, WasteRequest


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate distance between two coordinates using Haversine formula.
    Returns distance in kilometers.
    """
    R = 6371  # Earth's radius in km
    
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c


def get_location_coords(obj) -> tuple[float, float]:
    """Extract latitude and longitude from a location object (WasteRequest or Bin)."""
    if isinstance(obj, WasteRequest):
        lat = obj.photo_latitude or obj.latitude
        lon = obj.photo_longitude or obj.longitude
    else:  # Bin
        lat = obj.latitude
        lon = obj.longitude
    
    if lat and lon:
        return float(lat), float(lon)
    return None


def get_ml_info(obj) -> dict:
    """Extract ML prediction info from a WasteRequest."""
    if not isinstance(obj, WasteRequest):
        return {'prediction': None, 'confidence': None, 'reviewed': False}
    
    # Map severity (low/medium/high) to user's HIGH/MEDIUM/LOW
    severity_map = {'high': 'HIGH', 'medium': 'MEDIUM', 'low': 'LOW'}
    pred = severity_map.get(obj.severity) if obj.severity else None
    conf = float(obj.ml_confidence) / 100.0 if obj.ml_confidence else None
    reviewed = not obj.needs_manual_review if obj.needs_manual_review is not None else True
    
    return {
        'prediction': pred,
        'confidence': conf,
        'reviewed': reviewed,
    }


class RouteOptimizer:
    """Optimizes waste pickup routes using nearest neighbor algorithm."""
    
    def __init__(self, start_location: tuple[float, float]):
        """Initialize with driver's starting location."""
        self.start_lat, self.start_lon = start_location
        self.route_points = []
        self.total_distance = 0.0
    
def optimize_nearest_neighbor(self, locations: list) -> list[dict]:
        """
        Optimize route using nearest neighbor algorithm.
        
        Args:
            locations: List of (id, type, lat, lon, ml_info) tuples
                      where type is 'request' or 'bin', ml_info is dict
         
        Returns:
            Optimized list of waypoints with coordinates and ML info
        """
        if not locations:
            return []
        
        unvisited = list(locations)
        current_lat, current_lon = self.start_lat, self.start_lon
        optimized_route = []
        total_distance = 0.0
        
        while unvisited:
            # Find nearest unvisited location
            nearest_idx = 0
            nearest_distance = float('inf')
            
            for idx, loc in enumerate(unvisited):
                lat, lon = loc[2], loc[3]
                dist = haversine_distance(current_lat, current_lon, lat, lon)
                if dist < nearest_distance:
                    nearest_distance = dist
                    nearest_idx = idx
            
            # Move to nearest location
            location_id, location_type, lat, lon, ml_info = unvisited.pop(nearest_idx)
            optimized_route.append({
                'id': location_id,
                'type': location_type,
                'latitude': lat,
                'longitude': lon,
                'distance_from_previous': nearest_distance,
                'ml_prediction': ml_info.get('prediction'),
                'ml_confidence': ml_info.get('confidence'),
                'ml_reviewed': ml_info.get('reviewed', False),
            })
            
            total_distance += nearest_distance
            current_lat, current_lon = lat, lon
        
        self.route_points = optimized_route
        self.total_distance = total_distance
        
        return optimized_route
    
    def get_route_data(self) -> dict:
        """Get complete route data with waypoints and metadata."""
        return {
            'waypoints': self.route_points,
            'total_distance_km': round(self.total_distance, 2),
            'total_stops': len(self.route_points),
            'start_location': {
                'latitude': self.start_lat,
                'longitude': self.start_lon,
            },
        }


def get_depot_location():
    """Read depot location from SystemSettings. Falls back to Pokhara."""
    try:
        from .models import SystemSettings
        setting = SystemSettings.objects.get(key='depot_location')
        val = setting.value  # JSONField: {"latitude": 28.2096, "longitude": 83.9856}
        return (float(val['latitude']), float(val['longitude']))
    except (SystemSettings.DoesNotExist, KeyError, TypeError, ValueError):
        return (28.2096, 83.9856)  # Default: Pokhara


def generate_optimal_route(driver, waste_request_ids=None, bin_ids=None):
    # CHANGED: always start from depot, not driver GPS
    start_loc = get_depot_location()
    
    locations = []
    if waste_request_ids:
        requests = WasteRequest.objects.filter(id__in=waste_request_ids).prefetch_related('photos')
        for req in requests:
            coords = get_location_coords(req)
            if coords:
                ml_info = get_ml_info(req)
                locations.append((req.id, 'request', coords[0], coords[1], ml_info))

    if bin_ids:
        bins = Bin.objects.filter(id__in=bin_ids)
        for bin_obj in bins:
            coords = get_location_coords(bin_obj)
            if coords:
                locations.append((bin_obj.id, 'bin', coords[0], coords[1], {}))

    if not locations:
        return {'error': 'No valid locations to optimize'}

    optimizer = RouteOptimizer(start_loc)
    optimizer.optimize_nearest_neighbor(locations)
    return optimizer.get_route_data()