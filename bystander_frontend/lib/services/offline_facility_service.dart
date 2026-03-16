import 'dart:math' as math;

import 'package:csv/csv.dart';
import 'package:flutter/services.dart' show rootBundle;

class OfflineHospital {
  final String id;
  final String name;
  final String address;
  final double latitude;
  final double longitude;
  final double distanceKm;

  const OfflineHospital({
    required this.id,
    required this.name,
    required this.address,
    required this.latitude,
    required this.longitude,
    required this.distanceKm,
  });
}

class _HospitalBase {
  final String id;
  final String name;
  final String address;
  final double latitude;
  final double longitude;

  const _HospitalBase({
    required this.id,
    required this.name,
    required this.address,
    required this.latitude,
    required this.longitude,
  });
}

class OfflineFacilityService {
  OfflineFacilityService._();
  static final OfflineFacilityService instance = OfflineFacilityService._();

  static List<_HospitalBase>? _cachedHospitals;

  Future<List<_HospitalBase>> _loadHospitals() async {
    final cached = _cachedHospitals;
    if (cached != null) {
      return cached;
    }

    final raw = await rootBundle.loadString('assets/facilities.csv');
    final rows = const CsvToListConverter(
      shouldParseNumbers: false,
      eol: '\n',
    ).convert(raw);

    if (rows.isEmpty) {
      _cachedHospitals = const [];
      return _cachedHospitals!;
    }

    final headers = rows.first
        .map((e) => e.toString().trim().replaceFirst('\ufeff', ''))
        .toList();

    int idxOf(List<String> candidates) {
      for (final candidate in candidates) {
        final idx = headers.indexOf(candidate);
        if (idx >= 0) return idx;
      }
      return -1;
    }

    final idIdx = idxOf(['ID', '_id']);
    final nameIdx = idxOf(['Agency', 'Name', 'Hospital']);
    final addressIdx = idxOf(['Address', 'ที่อยู่']);
    final latIdx = idxOf(['Lat', 'Latitude', 'lat']);
    final lngIdx = idxOf(['Long', 'Lng', 'Longitude', 'long']);

    if (nameIdx < 0 || latIdx < 0 || lngIdx < 0) {
      _cachedHospitals = const [];
      return _cachedHospitals!;
    }

    final hospitals = <_HospitalBase>[];

    for (int i = 1; i < rows.length; i++) {
      final row = rows[i];
      if (row.length <= math.max(nameIdx, math.max(latIdx, lngIdx))) {
        continue;
      }

      final name = row[nameIdx].toString().trim();
      final address = (addressIdx >= 0 && addressIdx < row.length)
          ? row[addressIdx].toString().trim()
          : '';
      final lat = double.tryParse(row[latIdx].toString().trim());
      final lng = double.tryParse(row[lngIdx].toString().trim());

      if (name.isEmpty || lat == null || lng == null) {
        continue;
      }

      final id = (idIdx >= 0 && idIdx < row.length)
          ? row[idIdx].toString().trim()
          : '$i';

      hospitals.add(
        _HospitalBase(
          id: id,
          name: name,
          address: address,
          latitude: lat,
          longitude: lng,
        ),
      );
    }

    _cachedHospitals = hospitals;
    return hospitals;
  }

  static double _haversineKm(
    double lat1,
    double lon1,
    double lat2,
    double lon2,
  ) {
    const r = 6371.0;
    final dLat = _toRadians(lat2 - lat1);
    final dLon = _toRadians(lon2 - lon1);
    final a = math.sin(dLat / 2) * math.sin(dLat / 2) +
        math.cos(_toRadians(lat1)) *
            math.cos(_toRadians(lat2)) *
            math.sin(dLon / 2) *
            math.sin(dLon / 2);
    final c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a));
    return r * c;
  }

  static double _toRadians(double degree) => degree * (math.pi / 180.0);

  Future<List<OfflineHospital>> findNearestHospitals({
    required double userLatitude,
    required double userLongitude,
    int limit = 20,
  }) async {
    final hospitals = await _loadHospitals();
    final nearest = hospitals
        .map(
          (h) => OfflineHospital(
            id: h.id,
            name: h.name,
            address: h.address,
            latitude: h.latitude,
            longitude: h.longitude,
            distanceKm: _haversineKm(
              userLatitude,
              userLongitude,
              h.latitude,
              h.longitude,
            ),
          ),
        )
        .toList()
      ..sort((a, b) => a.distanceKm.compareTo(b.distanceKm));

    if (limit <= 0 || nearest.length <= limit) {
      return nearest;
    }
    return nearest.take(limit).toList();
  }
}
