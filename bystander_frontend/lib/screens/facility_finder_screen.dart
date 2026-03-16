import 'package:bystander_frontend/services/offline_facility_service.dart';
import 'package:bystander_frontend/services/runtime_asset_mode.dart';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart' as gmap;
import 'package:latlong2/latlong.dart' as latlng;
import 'package:url_launcher/url_launcher.dart';

class Facility {
  final String placeId;
  final String name;
  final String address;
  final double latitude;
  final double longitude;
  final double rating;
  final int userRatingsTotal;
  final bool? openNow;
  final String phoneNumber;
  final String website;
  final List<String> types;
  final double? distanceKm;

  Facility({
    required this.placeId,
    required this.name,
    required this.address,
    required this.latitude,
    required this.longitude,
    required this.rating,
    required this.userRatingsTotal,
    this.openNow,
    required this.phoneNumber,
    required this.website,
    required this.types,
    this.distanceKm,
  });

  factory Facility.fromJson(Map<String, dynamic> json) {
    return Facility(
      placeId: json['place_id'] ?? '',
      name: json['name'] ?? '',
      address: json['address'] ?? '',
      latitude: (json['latitude'] ?? 0).toDouble(),
      longitude: (json['longitude'] ?? 0).toDouble(),
      rating: (json['rating'] ?? 0).toDouble(),
      userRatingsTotal: json['user_ratings_total'] ?? 0,
      openNow: json['open_now'],
      phoneNumber: json['phone_number'] ?? '',
      website: json['website'] ?? '',
      types: List<String>.from(json['types'] ?? []),
      distanceKm: (json['distance_km'] is num)
          ? (json['distance_km'] as num).toDouble()
          : null,
    );
  }
}

class FacilityFinderScreen extends StatefulWidget {
  final List<Facility> facilities;
  final double userLatitude;
  final double userLongitude;
  final String facilityType;
  final String severity;

  const FacilityFinderScreen({
    super.key,
    required this.facilities,
    required this.userLatitude,
    required this.userLongitude,
    required this.facilityType,
    required this.severity,
  });

  @override
  State<FacilityFinderScreen> createState() => _FacilityFinderScreenState();
}

class _FacilityFinderScreenState extends State<FacilityFinderScreen> {
  final MapController _mapController = MapController();
  gmap.GoogleMapController? _googleMapController;
  int? _selectedFacilityIndex;
  bool _loadingOffline = false;
  bool _usedOfflineFallback = false;
  String _offlineError = '';
  List<Facility> _facilities = const [];

  @override
  void dispose() {
    _googleMapController?.dispose();
    super.dispose();
  }

  List<Facility> _filterHumanFacilities(List<Facility> input) {
    bool isVet(Facility f) {
      final name = f.name.toLowerCase();
      final types = f.types.map((e) => e.toLowerCase()).toList();
      return name.contains('vet') ||
          name.contains('veterinary') ||
          name.contains('สัตว') ||
          types.contains('veterinary_care');
    }

    return input.where((f) => !isVet(f)).toList();
  }

  @override
  void initState() {
    super.initState();
    _initializeFacilities();
  }

  Future<void> _initializeFacilities() async {
    final onlineFacilities = _filterHumanFacilities(widget.facilities);
    if (onlineFacilities.isNotEmpty) {
      setState(() {
        _facilities = onlineFacilities;
      });
      return;
    }

    await _loadOfflineFacilities();
  }

  Future<void> _loadOfflineFacilities() async {
    setState(() {
      _loadingOffline = true;
      _offlineError = '';
    });

    try {
      final nearest =
          await OfflineFacilityService.instance.findNearestHospitals(
        userLatitude: widget.userLatitude,
        userLongitude: widget.userLongitude,
        limit: 30,
      );

      final converted = nearest
          .map(
            (h) => Facility(
              placeId: 'offline_${h.id}',
              name: h.name,
              address: h.address,
              latitude: h.latitude,
              longitude: h.longitude,
              rating: 0,
              userRatingsTotal: 0,
              openNow: null,
              phoneNumber: '',
              website: '',
              types: const ['hospital', 'offline_dataset'],
              distanceKm: h.distanceKm,
            ),
          )
          .toList();

      if (!mounted) return;
      setState(() {
        _facilities = converted;
        _usedOfflineFallback = true;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _offlineError = 'โหลดข้อมูลโรงพยาบาลออฟไลน์ไม่สำเร็จ';
      });
    } finally {
      if (mounted) {
        setState(() {
          _loadingOffline = false;
        });
      }
    }
  }

  Future<void> _openInMaps(Facility facility) async {
    final Uri googleMapsUrl = Uri.parse(
      'https://www.google.com/maps/search/?api=1&query=${facility.latitude},${facility.longitude}',
    );

    if (await canLaunchUrl(googleMapsUrl)) {
      await launchUrl(googleMapsUrl, mode: LaunchMode.externalApplication);
    } else {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('ไม่สามารถเปิดแผนที่ได้')),
        );
      }
    }
  }

  Future<void> _makePhoneCall(String phoneNumber) async {
    if (phoneNumber.isEmpty) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('ไม่มีหมายเลขโทรศัพท์')),
        );
      }
      return;
    }

    final Uri launchUri = Uri(scheme: 'tel', path: phoneNumber);
    if (await canLaunchUrl(launchUri)) {
      await launchUrl(launchUri);
    } else {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('ไม่สามารถโทรออกไปยัง $phoneNumber ได้')),
        );
      }
    }
  }

  Future<void> _openWebsite(String website) async {
    if (website.isEmpty) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('ไม่มีเว็บไซต์')),
        );
      }
      return;
    }

    final Uri url = Uri.parse(website);
    if (await canLaunchUrl(url)) {
      await launchUrl(url, mode: LaunchMode.externalApplication);
    } else {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('ไม่สามารถเปิดเว็บไซต์ได้')),
        );
      }
    }
  }

  void _moveCameraToFacility(Facility facility) {
    _googleMapController?.animateCamera(
      gmap.CameraUpdate.newLatLngZoom(
        gmap.LatLng(facility.latitude, facility.longitude),
        14,
      ),
    );
    _mapController.move(
      latlng.LatLng(facility.latitude, facility.longitude),
      14,
    );
  }

  List<Marker> _buildMarkers() {
    final markers = <Marker>[
      Marker(
        point: latlng.LatLng(widget.userLatitude, widget.userLongitude),
        width: 42,
        height: 42,
        child: const Icon(Icons.my_location, color: Colors.blue, size: 30),
      ),
    ];

    for (int i = 0; i < _facilities.length; i++) {
      final facility = _facilities[i];
      final bool isSelected = _selectedFacilityIndex == i;
      markers.add(
        Marker(
          point: latlng.LatLng(facility.latitude, facility.longitude),
          width: 46,
          height: 46,
          child: GestureDetector(
            onTap: () {
              setState(() {
                _selectedFacilityIndex = i;
              });
            },
            child: Icon(
              Icons.local_hospital,
              color: isSelected
                  ? Colors.deepOrange
                  : (widget.severity == 'critical'
                      ? Colors.red.shade700
                      : Colors.green.shade700),
              size: isSelected ? 34 : 28,
            ),
          ),
        ),
      );
    }

    return markers;
  }

  Set<gmap.Marker> _buildGoogleMarkers() {
    final markers = <gmap.Marker>{
      gmap.Marker(
        markerId: const gmap.MarkerId('user_location'),
        position: gmap.LatLng(widget.userLatitude, widget.userLongitude),
        icon: gmap.BitmapDescriptor.defaultMarkerWithHue(
          gmap.BitmapDescriptor.hueBlue,
        ),
        infoWindow: const gmap.InfoWindow(title: 'ตำแหน่งของคุณ'),
      ),
    };

    for (int i = 0; i < _facilities.length; i++) {
      final facility = _facilities[i];
      markers.add(
        gmap.Marker(
          markerId: gmap.MarkerId(facility.placeId),
          position: gmap.LatLng(facility.latitude, facility.longitude),
          icon: gmap.BitmapDescriptor.defaultMarkerWithHue(
            widget.severity == 'critical'
                ? gmap.BitmapDescriptor.hueRed
                : gmap.BitmapDescriptor.hueGreen,
          ),
          infoWindow: gmap.InfoWindow(
            title: facility.name,
            snippet: facility.address,
          ),
          onTap: () {
            setState(() {
              _selectedFacilityIndex = i;
            });
          },
        ),
      );
    }
    return markers;
  }

  @override
  Widget build(BuildContext context) {
    final TextTheme appTextTheme = Theme.of(context).textTheme;
    final ColorScheme appColorScheme = Theme.of(context).colorScheme;
    final facilities = _facilities;
    final bool useOnlineMaps = RuntimeAssetMode.useOnlineMaps;

    return Scaffold(
      appBar: AppBar(
        title: Text(
          widget.facilityType == 'hospital'
              ? 'โรงพยาบาลใกล้ที่สุด'
              : 'คลินิก/โรงพยาบาลใกล้ที่สุด',
        ),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => Navigator.of(context).pop(),
        ),
      ),
      body: Column(
        children: [
          if (_usedOfflineFallback)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(10),
              color: Colors.blueGrey.shade50,
              child: Text(
                'กำลังใช้ข้อมูลโรงพยาบาลออฟไลน์จากไฟล์ในเครื่อง',
                style: appTextTheme.bodySmall,
                textAlign: TextAlign.center,
              ),
            ),
          if (widget.severity == 'critical')
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              color: Colors.red.shade700,
              child: Row(
                children: [
                  const Icon(Icons.warning, color: Colors.white),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'สถานการณ์ฉุกเฉิน - กรุณาไปโรงพยาบาลโดยเร็ว',
                      style: appTextTheme.bodyMedium?.copyWith(
                        color: Colors.white,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          Expanded(
            flex: 2,
            child: _loadingOffline
                ? const Center(child: CircularProgressIndicator())
                : facilities.isEmpty
                    ? Center(
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(
                              Icons.location_off,
                              size: 64,
                              color:
                                  appColorScheme.primary.withValues(alpha: 0.5),
                            ),
                            const SizedBox(height: 16),
                            Text(
                              _offlineError.isNotEmpty
                                  ? _offlineError
                                  : 'ไม่พบข้อมูลโรงพยาบาลใกล้เคียง',
                              style: appTextTheme.bodyLarge,
                            ),
                          ],
                        ),
                      )
                    : (useOnlineMaps
                        ? gmap.GoogleMap(
                            initialCameraPosition: gmap.CameraPosition(
                              target: gmap.LatLng(
                                widget.userLatitude,
                                widget.userLongitude,
                              ),
                              zoom: 11,
                            ),
                            onMapCreated:
                                (gmap.GoogleMapController controller) {
                              _googleMapController = controller;
                            },
                            markers: _buildGoogleMarkers(),
                            myLocationButtonEnabled: true,
                            zoomControlsEnabled: true,
                            mapToolbarEnabled: false,
                          )
                        : FlutterMap(
                            mapController: _mapController,
                            options: MapOptions(
                              initialCenter: latlng.LatLng(
                                widget.userLatitude,
                                widget.userLongitude,
                              ),
                              initialZoom: 11,
                            ),
                            children: [
                              TileLayer(
                                urlTemplate:
                                    'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                                userAgentPackageName: 'com.bystander.frontend',
                              ),
                              MarkerLayer(markers: _buildMarkers()),
                            ],
                          )),
          ),
          Expanded(
            flex: 3,
            child: facilities.isEmpty
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(16.0),
                      child: Text(
                        'กรุณาโทร 1669 เพื่อขอความช่วยเหลือ',
                        style: appTextTheme.titleMedium?.copyWith(
                          color: appColorScheme.error,
                        ),
                        textAlign: TextAlign.center,
                      ),
                    ),
                  )
                : ListView.builder(
                    padding: const EdgeInsets.all(8),
                    itemCount: facilities.length,
                    itemBuilder: (context, index) {
                      final facility = facilities[index];
                      final isSelected = _selectedFacilityIndex == index;

                      return Card(
                        elevation: isSelected ? 4 : 1,
                        margin: const EdgeInsets.symmetric(
                          vertical: 6,
                          horizontal: 8,
                        ),
                        color:
                            isSelected ? appColorScheme.primaryContainer : null,
                        child: ListTile(
                          leading: CircleAvatar(
                            backgroundColor: widget.severity == 'critical'
                                ? Colors.red.shade700
                                : appColorScheme.primary,
                            child: Text(
                              '${index + 1}',
                              style: const TextStyle(
                                color: Colors.white,
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                          ),
                          title: Text(
                            facility.name,
                            style: appTextTheme.titleSmall?.copyWith(
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                          subtitle: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const SizedBox(height: 4),
                              Text(
                                facility.address,
                                style: appTextTheme.bodySmall,
                              ),
                              if (facility.distanceKm != null) ...[
                                const SizedBox(height: 4),
                                Text(
                                  'ระยะทางประมาณ ${facility.distanceKm!.toStringAsFixed(1)} กม.',
                                  style: appTextTheme.bodySmall?.copyWith(
                                    color: Colors.blueGrey.shade700,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                              ],
                              if (facility.phoneNumber.isNotEmpty) ...[
                                const SizedBox(height: 4),
                                InkWell(
                                  onTap: () =>
                                      _makePhoneCall(facility.phoneNumber),
                                  child: Row(
                                    children: [
                                      Icon(
                                        Icons.phone,
                                        size: 14,
                                        color: appColorScheme.primary,
                                      ),
                                      const SizedBox(width: 4),
                                      Expanded(
                                        child: Text(
                                          facility.phoneNumber,
                                          style:
                                              appTextTheme.bodySmall?.copyWith(
                                            color: appColorScheme.primary,
                                            decoration:
                                                TextDecoration.underline,
                                          ),
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                              ],
                            ],
                          ),
                          trailing: PopupMenuButton<String>(
                            icon: const Icon(Icons.more_vert),
                            onSelected: (value) {
                              switch (value) {
                                case 'navigate':
                                  _openInMaps(facility);
                                  break;
                                case 'call':
                                  _makePhoneCall(facility.phoneNumber);
                                  break;
                                case 'website':
                                  _openWebsite(facility.website);
                                  break;
                              }
                            },
                            itemBuilder: (context) => [
                              const PopupMenuItem(
                                value: 'navigate',
                                child: Row(
                                  children: [
                                    Icon(Icons.directions),
                                    SizedBox(width: 8),
                                    Text('นำทาง'),
                                  ],
                                ),
                              ),
                              if (facility.phoneNumber.isNotEmpty)
                                const PopupMenuItem(
                                  value: 'call',
                                  child: Row(
                                    children: [
                                      Icon(Icons.phone),
                                      SizedBox(width: 8),
                                      Text('โทร'),
                                    ],
                                  ),
                                ),
                              if (facility.website.isNotEmpty)
                                const PopupMenuItem(
                                  value: 'website',
                                  child: Row(
                                    children: [
                                      Icon(Icons.language),
                                      SizedBox(width: 8),
                                      Text('เว็บไซต์'),
                                    ],
                                  ),
                                ),
                            ],
                          ),
                          onTap: () {
                            setState(() {
                              _selectedFacilityIndex = index;
                            });
                            _moveCameraToFacility(facility);
                          },
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}
