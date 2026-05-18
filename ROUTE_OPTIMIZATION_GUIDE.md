# Route Optimization & Planning Feature

## Overview
Drivers can now generate optimal waste collection routes that minimize travel distance. Routes are visible to drivers, admins, and users in real-time with live GPS tracking on an interactive map.

---

## Features Implemented

### ✅ Automatic Route Optimization
- Uses **Nearest Neighbor Algorithm** to find shortest distance between pickup points
- Calculates total route distance in kilometers
- Includes starting location for reference

### ✅ Interactive Map Visualization
- Built with **Leaflet.js** (no API keys required)
- Shows driver start location (blue circle)
- Shows pickup waypoints with green markers numbered 1-N
- Draws route line connecting all stops
- Click waypoints to see details (distance from previous stop)

### ✅ Real-Time Updates
- WebSocket broadcasts route updates to all connected users
- Driver location tracked live
- Route status updates (Planned → Active → Completed)

### ✅ Multi-User Access
- **Drivers**: Can generate and view their own routes
- **Admins**: Can create routes for any driver, view all routes
- **Users**: Can see routes assigned to their waste requests (read-only)

---

## How to Use

### For Drivers or Admins

1. **Navigate to Route Planning**
   - Go to: `http://localhost:8000/route-planning/`
   
2. **Select a Driver**
   - Choose from dropdown (defaults to current user if driver)

3. **Choose Pickup Locations**
   - Click **"Select Requests"** button
   - Choose waste requests to include in route
   - Confirm selection

4. **Generate Optimal Route**
   - Click **"Generate Optimal Route"** button
   - System calculates shortest path automatically
   - Map displays optimized waypoints

5. **Review Route**
   - View route summary: total distance & stops
   - See waypoint list in sidebar (numbered 1-N)
   - Inspect each waypoint by clicking it

6. **Start Route**
   - Click **"Start Route"** button
   - Status changes from "Planned" → "Active"
   - Real-time location broadcast begins

7. **Complete Route**
   - Once all stops finished
   - Status changes from "Active" → "Completed"

---

## API Endpoints

### Generate Optimal Route
```
POST /api/routes/generate_optimal/
Authorization: Bearer <token>

{
  "driver_id": 1,
  "waste_request_ids": [10, 15, 20],
  "bin_ids": [5, 8],
  "planned_date": "2024-05-20"
}

Response:
{
  "route": { /* RouteSerializer data */ },
  "route_data": {
    "waypoints": [
      {
        "id": 10,
        "type": "request",
        "latitude": 40.7128,
        "longitude": -74.0060,
        "distance_from_previous": 2.45
      },
      ...
    ],
    "total_distance_km": 12.34,
    "total_stops": 3,
    "start_location": {
      "latitude": 40.7580,
      "longitude": -73.9855
    }
  }
}
```

### Start Route
```
PATCH /api/routes/{route_id}/start_route/
Authorization: Bearer <token>

Response: Route object with status='active'
```

### Complete Route
```
PATCH /api/routes/{route_id}/complete_route/
Authorization: Bearer <token>

Response: Route object with status='completed'
```

---

## Technical Details

### Route Optimization Algorithm
Uses **Nearest Neighbor Heuristic**:

1. Start at driver's current location
2. For each unvisited pickup point:
   - Calculate distance using Haversine formula (great-circle distance)
   - Select the nearest one
   - Move there and record cumulative distance
3. Return ordered waypoints with distances

**Complexity**: O(n²) where n = number of stops

### Haversine Formula
Calculates shortest distance between two coordinates on Earth:
```
distance = 2R * atan2(√a, √(1-a))
where a = sin²(Δφ/2) + cos φ₁ * cos φ₂ * sin²(Δλ/2)
```
Returns distance in kilometers.

### Real-Time Broadcasting
Route updates sent via WebSocket to channel group `driver_locations`:
```javascript
// On client (browser)
const ws = new WebSocket(
  `ws://localhost:8000/ws/driver-locations/?token=<jwt_token>`
);

ws.onmessage = (e) => {
  const data = JSON.parse(e.data);
  if (data.type === 'route_update') {
    // Update map with new waypoints
    console.log(data.waypoints);
  }
};
```

---

## Database

### Route Model (Already Exists)
```python
class Route(models.Model):
    driver = ForeignKey(Driver)
    vehicle = ForeignKey(Vehicle)
    waste_requests = ManyToManyField(WasteRequest)
    bins = ManyToManyField(Bin)
    status = CharField(choices=[
        'planned', 'active', 'completed', 'cancelled'
    ])
    planned_date = DateField()
    started_at = DateTimeField(nullable)
    completed_at = DateTimeField(nullable)
    total_distance_km = FloatField()
```

---

## Files Created/Modified

### New Files
- ✅ `api_app/route_optimizer.py` - Optimization algorithms
- ✅ `templates/web_app/route_planning.html` - UI interface

### Modified Files
- ✅ `api_app/views.py` - Added `generate_optimal` action
- ✅ `api_app/consumers.py` - Added `route_update` handler
- ✅ `web_app/views.py` - Added `RoutePlanningView`
- ✅ `web_app/urls.py` - Added `/route-planning/` URL

---

## Future Enhancements

### Possible Improvements
1. **Advanced Algorithms**: TSP (Traveling Salesman Problem) solver
2. **Traffic-Aware**: Real-time traffic data integration
3. **Time Windows**: Respect scheduled pickup times
4. **Vehicle Constraints**: Capacity, vehicle type requirements
5. **Safety Scoring**: Avoid high-risk areas (if data available)
6. **Import/Export**: Save/load routes as GPX files
7. **Driver Analytics**: Performance metrics per route
8. **Mobile App**: Native iOS/Android for drivers

---

## Troubleshooting

### Map Not Loading
- Ensure browser allows Leaflet.js CDN
- Check browser console for errors
- Verify Leaflet CSS/JS loaded correctly

### Route Not Generating
- Ensure driver has valid coordinates (latitude/longitude)
- Check that waste requests have pickup coordinates
- Verify user has correct permissions

### WebSocket Not Updating
- Check JWT token is valid (not expired)
- Verify WebSocket URL includes token query parameter
- Check Django Channels configured correctly

---

## Example Workflow

```bash
# 1. Get drivers
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/drivers/

# 2. Get pending waste requests
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/waste-requests/?status=pending

# 3. Generate optimal route
curl -X POST -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/routes/generate_optimal/ \
  -d '{
    "driver_id": 1,
    "waste_request_ids": [1, 2, 3],
    "planned_date": "2024-05-20"
  }'

# 4. Start the route
curl -X PATCH -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/routes/1/start_route/

# 5. Complete the route
curl -X PATCH -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/routes/1/complete_route/
```

---

## Support

For issues or questions:
1. Check browser console for JavaScript errors
2. Check Django server logs for API errors
3. Verify all waste requests have valid coordinates
4. Ensure JWT token is not expired
5. Test with curl before testing in browser

