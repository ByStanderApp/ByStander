import 'package:bystander_frontend/services/api_service.dart';
import 'package:bystander_frontend/services/medical_context_cache_service.dart';
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

  group('payload builders', () {
    test('omits null GPS fields from workflow payload', () {
      final payload = buildAgentWorkflowPayload(
        scenario: 'test',
        callerUserId: 'caller',
        targetUserId: 'target',
      );
      expect(payload.containsKey('latitude'), isFalse);
      expect(payload.containsKey('longitude'), isFalse);
    });

    test('builds medical context with relationship pronoun', () {
      final payload = buildMedicalContextPayload(
        individuals: const [
          CachedMedicalPerson(
            uid: 'friend-1',
            name: 'Dao',
            relationship: 'แม่',
            conditions: ['asthma'],
          ),
        ],
        callerUserId: 'caller',
        targetUserId: 'friend-1',
      );
      final individuals = payload['individuals'] as List<dynamic>;
      final first = individuals.first as Map<String, dynamic>;
      expect(first['pronoun'], 'she');
      expect(first['is_target'], true);
    });

    test('detects when cached people have no medical history', () {
      expect(
        hasMedicalHistoryEntries(const [
          CachedMedicalPerson(uid: '1', name: 'No history'),
        ]),
        isFalse,
      );
    });
  });

  group('CallScriptResponse parsing', () {
    test('parses used medical history list', () {
      final parsed = CallScriptResponse.fromJson({
        'call_script': 'แจ้งว่าผู้ป่วยมีโรคหอบหืด',
        'location_context': 'ใกล้ตลาด',
        'facilities': const [],
        'used_medical_history': ['asthma', 'penicillin allergy'],
      });
      expect(parsed.usedMedicalHistory, ['asthma', 'penicillin allergy']);
    });
  });
}
