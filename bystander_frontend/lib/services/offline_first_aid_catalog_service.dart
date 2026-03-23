import 'dart:convert';

import 'package:flutter/services.dart' show rootBundle;

class OfflineFirstAidMatch {
  final String caseNameTh;
  final String keywords;
  final String instructions;
  final String severity;
  final String facilityType;

  const OfflineFirstAidMatch({
    required this.caseNameTh,
    required this.keywords,
    required this.instructions,
    required this.severity,
    required this.facilityType,
  });
}

class OfflineFirstAidCatalogService {
  OfflineFirstAidCatalogService._();
  static final OfflineFirstAidCatalogService instance =
      OfflineFirstAidCatalogService._();

  List<OfflineFirstAidMatch>? _cachedItems;

  Future<List<OfflineFirstAidMatch>> _loadCatalog() async {
    if (_cachedItems != null) {
      return _cachedItems!;
    }

    final raw = await rootBundle.loadString('assets/general_first_aid_catalog.json');
    final payload = jsonDecode(raw);
    final items = (payload['items'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(
          (row) => OfflineFirstAidMatch(
            caseNameTh: (row['case_name_th'] ?? '').toString().trim(),
            keywords: (row['keywords'] ?? '').toString().trim(),
            instructions: (row['instructions'] ?? '').toString().trim(),
            severity: _normalizeSeverity((row['severity'] ?? 'none').toString()),
            facilityType:
                _normalizeFacilityType((row['facility_type'] ?? 'none').toString()),
          ),
        )
        .where((item) => item.instructions.isNotEmpty)
        .toList();

    _cachedItems = items;
    return items;
  }

  Future<OfflineFirstAidMatch?> searchBestMatch(String prompt) async {
    final query = _normalize(prompt);
    if (query.isEmpty) {
      return null;
    }

    final items = await _loadCatalog();
    if (items.isEmpty) {
      return null;
    }

    OfflineFirstAidMatch? best;
    int bestScore = 0;

    for (final item in items) {
      final score = _score(query: query, item: item);
      if (score > bestScore) {
        bestScore = score;
        best = item;
      }
    }

    return bestScore > 0 ? best : null;
  }

  static int _score({
    required String query,
    required OfflineFirstAidMatch item,
  }) {
    final caseName = _normalize(item.caseNameTh);
    final keywords = _normalize(item.keywords);
    final instructions = _normalize(item.instructions);
    final combined = '$caseName $keywords $instructions';

    var score = 0;
    if (combined.contains(query)) {
      score += 20;
    }
    if (caseName.contains(query)) {
      score += 12;
    }
    if (keywords.contains(query)) {
      score += 10;
    }
    if (instructions.contains(query)) {
      score += 6;
    }

    final tokens = _tokens(query);
    for (final token in tokens) {
      if (caseName.contains(token)) {
        score += 4;
      }
      if (keywords.contains(token)) {
        score += 3;
      }
      if (instructions.contains(token)) {
        score += 1;
      }
    }
    return score;
  }

  static Set<String> _tokens(String text) {
    return text
        .split(RegExp(r'[\s,.;:!?()\[\]{}\-_/\\]+'))
        .map(_normalize)
        .where((t) => t.length >= 2)
        .toSet();
  }

  static String _normalize(String value) {
    return value.toLowerCase().replaceAll(RegExp(r'\s+'), ' ').trim();
  }

  static String _normalizeSeverity(String value) {
    final normalized = _normalize(value);
    if (normalized == 'critical') {
      return 'critical';
    }
    if (normalized == 'moderate' || normalized == 'mild') {
      return normalized;
    }
    return 'none';
  }

  static String _normalizeFacilityType(String value) {
    final normalized = _normalize(value);
    if (normalized == 'hospital' || normalized == 'clinic') {
      return normalized;
    }
    return 'none';
  }
}
