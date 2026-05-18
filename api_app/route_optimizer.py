import math
from decimal import Decimal
from typing import List, Tuple, Dict
from api_app.models import WasteRequest, Bin, Route, Driver


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


def get_location_coords(obj) -> Tuple[float, float]:
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


class RouteOptimizer:
    """Optimizes waste pickup routes using nearest neighbor algorithm."""
    
    def __init__(self, start_location: Tuple[float, float]):
        """Initialize with driver's starting location."""
        self.start_lat, self.start_lon = start_location
        self.route_points = []
        self.total_distance = 0.0
    
    def optimize_nearest_neighbor(self, locations: List[Tuple[int, str, float, float]]) -> List[Dict]:
        """
        Optimize route using nearest neighbor algorithm.
        
        Args:
            locations: List of (id, type, lat, lon) tuples
                      where type is 'request' or 'bin'
        
        Returns:
            Optimized list of waypoints with coordinates
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
            
            for idx, (location_id, location_type, lat, lon) in enumerate(unvisited):
                dist = haversine_distance(current_lat, current_lon, lat, lon)
                if dist < nearest_distance:
                    nearest_distance = dist
                    nearest_idx = idx
            
            # Move to nearest location
            location_id, location_type, lat, lon = unvisited.pop(nearest_idx)
            optimized_route.append({
                'id': location_id,
                'type': location_type,
                'latitude': lat,
                'longitude': lon,
                'distance_from_previous': nearest_distance,
            })
            
            total_distance += nearest_distance
            current_lat, current_lon = lat, lon
        
        self.route_points = optimized_route
        self.total_distance = total_distance
        
        return optimized_route
    
    def get_route_data(self) -> Dict:
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
    except Exception:
        return (28.2096, 83.9856)  # Default: Pokhara


def generate_optimal_route(driver, waste_request_ids=None, bin_ids=None):
    # CHANGED: always start from depot, not driver GPS
    start_loc = get_depot_location()
    
    locations = []
    if waste_request_ids:
        requests = WasteRequest.objects.filter(id__in=waste_request_ids)
        for req in requests:
            coords = get_location_coords(req)
            if coords:
                locations.append((req.id, 'request', coords[0], coords[1]))

    if bin_ids:
        bins = Bin.objects.filter(id__in=bin_ids)
        for bin_obj in bins:
            coords = get_location_coords(bin_obj)
            if coords:
                locations.append((bin_obj.id, 'bin', coords[0], coords[1]))

    if not locations:
        return {'error': 'No valid locations to optimize'}

    optimizer = RouteOptimizer(start_loc)
    optimizer.optimize_nearest_neighbor(locations)
    return optimizer.get_route_data()