import 'package:flutter_test/flutter_test.dart';

import 'package:bystander_frontend/services/api_service.dart';

void main() {
  test('GuidanceResponse model parses expected fields', () {
    final parsed = GuidanceResponse.fromJson({
      'guidance': 'โทร 1669 ทันที',
      'severity': 'critical',
      'facility_type': 'hospital',
    });
    expect(parsed.guidance, 'โทร 1669 ทันที');
    expect(parsed.severity, 'critical');
    expect(parsed.facilityType, 'hospital');
  });
}
