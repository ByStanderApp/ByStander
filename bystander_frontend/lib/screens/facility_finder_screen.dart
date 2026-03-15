import 'package:flutter/material.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
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
  GoogleMapController? _mapController;
  int? _selectedFacilityIndex;
  final Set<Marker> _markers = {};

  List<Facility> _humanFacilities() {
    bool isVet(Facility f) {
      final name = f.name.toLowerCase();
      final types = f.types.map((e) => e.toLowerCase()).toList();
      return name.contains('vet') ||
          name.contains('veterinary') ||
          name.contains('สัตว') ||
          types.contains('veterinary_care');
    }

    return widget.facilities.where((f) => !isVet(f)).toList();
  }

  @override
  void initState() {
    super.initState();
    _createMarkers();
  }

  @override
  void dispose() {
    _mapController?.dispose();
    super.dispose();
  }

  void _createMarkers() {
    final facilities = _humanFacilities();
    // Add user location marker
    _markers.add(
      Marker(
        markerId: const MarkerId('user_location'),
        position: LatLng(widget.userLatitude, widget.userLongitude),
        icon: BitmapDescriptor.defaultMarkerWithHue(BitmapDescriptor.hueBlue),
        infoWindow: const InfoWindow(title: 'ตำแหน่งของคุณ'),
      ),
    );

    // Add facility markers
    for (int i = 0; i < facilities.length; i++) {
      final facility = facilities[i];
      _markers.add(
        Marker(
          markerId: MarkerId(facility.placeId),
          position: LatLng(facility.latitude, facility.longitude),
          icon: BitmapDescriptor.defaultMarkerWithHue(
            widget.severity == 'critical'
                ? BitmapDescriptor.hueRed
                : BitmapDescriptor.hueGreen,
          ),
          infoWindow: InfoWindow(
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
  }

  Future<void> _openInMaps(Facility facility) async {
    final Uri googleMapsUrl = Uri.parse(
      'https://www.google.com/maps/search/?api=1&query=${facility.latitude},${facility.longitude}&query_place_id=${facility.placeId}',
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
    _mapController?.animateCamera(
      CameraUpdate.newLatLngZoom(
        LatLng(facility.latitude, facility.longitude),
        15,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final TextTheme appTextTheme = Theme.of(context).textTheme;
    final ColorScheme appColorScheme = Theme.of(context).colorScheme;
    final facilities = _humanFacilities();

    return Scaffold(
      appBar: AppBar(
        title: Text(
          widget.facilityType == 'hospital'
              ? 'โรงพยาบาลใกล้เคียง'
              : 'คลินิกใกล้เคียง',
        ),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => Navigator.of(context).pop(),
        ),
      ),
      body: Column(
        children: [
          // Severity indicator
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

          // Map view
          Expanded(
            flex: 2,
            child: facilities.isEmpty
                ? Center(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(
                          Icons.location_off,
                          size: 64,
                          color: appColorScheme.primary.withOpacity(0.5),
                        ),
                        const SizedBox(height: 16),
                        Text(
                          'ไม่พบสถานพยาบาลในบริเวณใกล้เคียง',
                          style: appTextTheme.bodyLarge,
                        ),
                      ],
                    ),
                  )
                : GoogleMap(
                    initialCameraPosition: CameraPosition(
                      target: LatLng(widget.userLatitude, widget.userLongitude),
                      zoom: 12,
                    ),
                    markers: _markers,
                    onMapCreated: (GoogleMapController controller) {
                      _mapController = controller;
                    },
                    myLocationButtonEnabled: true,
                    zoomControlsEnabled: true,
                    mapToolbarEnabled: false,
                  ),
          ),

          // Facility list
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
                              const SizedBox(height: 4),
                              Row(
                                children: [
                                  if (facility.rating > 0) ...[
                                    Icon(
                                      Icons.star,
                                      size: 16,
                                      color: Colors.amber.shade700,
                                    ),
                                    const SizedBox(width: 4),
                                    Text(
                                      '${facility.rating.toStringAsFixed(1)} (${facility.userRatingsTotal})',
                                      style: appTextTheme.bodySmall,
                                    ),
                                    const SizedBox(width: 12),
                                  ],
                                  if (facility.openNow != null)
                                    Container(
                                      padding: const EdgeInsets.symmetric(
                                        horizontal: 6,
                                        vertical: 2,
                                      ),
                                      decoration: BoxDecoration(
                                        color: facility.openNow!
                                            ? Colors.green.shade100
                                            : Colors.red.shade100,
                                        borderRadius: BorderRadius.circular(4),
                                      ),
                                      child: Text(
                                        facility.openNow!
                                            ? 'เปิดอยู่'
                                            : 'ปิดแล้ว',
                                        style: appTextTheme.bodySmall?.copyWith(
                                          color: facility.openNow!
                                              ? Colors.green.shade900
                                              : Colors.red.shade900,
                                          fontWeight: FontWeight.bold,
                                        ),
                                      ),
                                    ),
                                ],
                              ),
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
