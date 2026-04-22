(function () {
    var reportsEl = document.getElementById('reports-data');
    var reports = reportsEl ? JSON.parse(reportsEl.textContent) : [];

    var STATUS_COLOR = {
        pending:     '#f59e0b',
        in_progress: '#3b82f6',
        solved:      '#22c55e'
    };

    var map = L.map('map');

    // CartoDB Voyager — works on localhost, no Referer required
    L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 19
    }).addTo(map);

    // Place markers
    reports.forEach(function (r) {
        var color = STATUS_COLOR[r.status] || '#888';
        var imgHtml = r.image
            ? '<img src="' + r.image + '" style="width:100%;border-radius:6px;margin-bottom:8px;">'
            : '';
        L.circleMarker([r.lat, r.lng], {
            radius: 10,
            fillColor: color,
            color: '#fff',
            weight: 2.5,
            opacity: 1,
            fillOpacity: 0.9
        }).addTo(map).bindPopup(
            '<div style="min-width:160px">' +
            imgHtml +
            '<strong>' + r.title + '</strong><br>' +
            '<span style="font-size:0.8rem;color:#64748b">' + r.description + '</span><br>' +
            '<div style="margin-top:6px;font-size:0.78rem">👤 ' + r.user + '&nbsp;&nbsp;📅 ' + r.created_at + '</div>' +
            '<div style="margin-top:4px"><span style="background:' + color + '22;color:' + color +
            ';padding:2px 8px;border-radius:10px;font-size:0.75rem;border:1px solid ' + color + '55">' +
            r.status.replace('_', ' ') + '</span></div>' +
            '</div>'
        );
    });

    // Fit bounds
    if (reports.length > 0) {
        map.fitBounds(
            reports.map(function (r) { return [r.lat, r.lng]; }),
            { padding: [50, 50] }
        );
    } else {
        map.setView([28.2096, 83.9856], 5);
    }

    // Nearest-neighbour TSP approximation
    function nearestNeighbour(pts) {
        if (pts.length === 0) return [];
        var remaining = pts.slice();
        var path = [remaining.splice(0, 1)[0]];
        while (remaining.length > 0) {
            var last = path[path.length - 1];
            var bestIdx = 0, bestDist = Infinity;
            remaining.forEach(function (p, i) {
                var d = Math.pow(p.lat - last.lat, 2) + Math.pow(p.lng - last.lng, 2);
                if (d < bestDist) { bestDist = d; bestIdx = i; }
            });
            path.push(remaining.splice(bestIdx, 1)[0]);
        }
        return path;
    }

    var routingControl = null;
    var routePolyline  = null;

    window.generateRoute = function () {
        var pts = reports
            .filter(function (r) { return r.status !== 'solved'; })
            .map(function (r) { return { lat: r.lat, lng: r.lng, title: r.title }; });

        if (pts.length === 0) {
            pts = reports.map(function (r) { return { lat: r.lat, lng: r.lng, title: r.title }; });
        }

        if (pts.length < 2) {
            document.getElementById('route-info').textContent =
                'Need at least 2 reports to generate a route.';
            return;
        }

        clearRoute();

        var optimised  = nearestNeighbour(pts);
        var waypoints  = optimised.map(function (p) { return L.latLng(p.lat, p.lng); });

        try {
            routingControl = L.Routing.control({
                waypoints: waypoints,
                routeWhileDragging: false,
                addWaypoints: false,
                lineOptions: {
                    styles: [{ color: '#22d3ee', opacity: 0.85, weight: 5 }]
                },
                createMarker: function (i, wp) {
                    return L.marker(wp.latLng, {
                        icon: L.divIcon({
                            className: '',
                            html: '<div style="background:#22d3ee;color:#0f172a;border-radius:50%;' +
                                  'width:26px;height:26px;display:flex;align-items:center;' +
                                  'justify-content:center;font-weight:700;font-size:0.85rem;' +
                                  'border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.4)">' +
                                  (i + 1) + '</div>',
                            iconSize: [26, 26],
                            iconAnchor: [13, 13]
                        })
                    }).bindPopup('Stop ' + (i + 1) + ': ' + optimised[i].title);
                }
            }).addTo(map);
        } catch (e) {
            // Fallback: simple polyline if LRM unavailable
            routePolyline = L.polyline(waypoints, {
                color: '#22d3ee', weight: 5, opacity: 0.85, dashArray: '10,6'
            }).addTo(map);
        }

        map.fitBounds(
            waypoints.map(function (w) { return [w.lat, w.lng]; }),
            { padding: [60, 60] }
        );

        document.getElementById('btn-clear-route').style.display = 'inline-flex';
        document.getElementById('route-info').textContent =
            'Route optimised across ' + optimised.length + ' locations (nearest-neighbour)';
    };

    window.clearRoute = function () {
        if (routingControl) { map.removeControl(routingControl); routingControl = null; }
        if (routePolyline)  { map.removeLayer(routePolyline);   routePolyline  = null; }
        document.getElementById('btn-clear-route').style.display = 'none';
        document.getElementById('route-info').textContent = '';
    };
})();