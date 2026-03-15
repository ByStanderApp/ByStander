import 'package:bystander_frontend/services/api_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('AgentWorkflowResponse parsing', () {
    test('parses emergency workflow response with facilities', () {
      final json = {
        'route': 'emergency_guidance',
        'is_emergency': true,
        'severity': 'critical',
        'facility_type': 'hospital',
        'guidance': '1. โทร 1669',
        'general_info': '',
        'call_script': 'แจ้งเหตุฉุกเฉิน',
        'triage_reason': 'วิกฤต',
        'facilities': [
          {
            'name': 'Hospital A',
            'address': 'Bangkok',
            'phone_number': '02-000-0000',
            'rating': 4.5,
            'distance_km': 1.2,
            'selection_reason': 'critical: sorted by shortest distance',
            'latitude': 13.7,
            'longitude': 100.5,
          }
        ],
      };

      final parsed = AgentWorkflowResponse.fromJson(json);
      expect(parsed.route, 'emergency_guidance');
      expect(parsed.isEmergency, true);
      expect(parsed.severity, 'critical');
      expect(parsed.facilities.length, 1);
      expect(parsed.facilities.first.name, 'Hospital A');
      expect(parsed.facilities.first.distanceKm, 1.2);
    });

    test('uses defaults for missing fields', () {
      final parsed = AgentWorkflowResponse.fromJson({});
      expect(parsed.route, 'general_info');
      expect(parsed.isEmergency, false);
      expect(parsed.severity, 'none');
      expect(parsed.facilities, isEmpty);
    });
  });
}
