import 'dart:convert';
import 'package:http/http.dart' as http;

// Data models
class GuidanceResponse {
  final String guidance;
  final String severity;
  final String facilityType;

  GuidanceResponse({
    required this.guidance,
    required this.severity,
    required this.facilityType,
  });

  factory GuidanceResponse.fromJson(Map<String, dynamic> json) {
    return GuidanceResponse(
      guidance: json['guidance'] ?? '',
      severity: json['severity'] ?? 'none',
      facilityType: json['facility_type'] ?? 'none',
    );
  }
}

class AgentFacility {
  final String name;
  final String address;
  final String phoneNumber;
  final double rating;
  final double distanceKm;
  final String selectionReason;
  final double? latitude;
  final double? longitude;

  AgentFacility({
    required this.name,
    required this.address,
    required this.phoneNumber,
    required this.rating,
    required this.distanceKm,
    required this.selectionReason,
    required this.latitude,
    required this.longitude,
  });

  factory AgentFacility.fromJson(Map<String, dynamic> json) {
    return AgentFacility(
      name: (json['name'] ?? '').toString(),
      address: (json['address'] ?? '').toString(),
      phoneNumber: (json['phone_number'] ?? '').toString(),
      rating:
          (json['rating'] is num) ? (json['rating'] as num).toDouble() : 0.0,
      distanceKm: (json['distance_km'] is num)
          ? (json['distance_km'] as num).toDouble()
          : 0.0,
      selectionReason: (json['selection_reason'] ?? '').toString(),
      latitude: (json['latitude'] is num)
          ? (json['latitude'] as num).toDouble()
          : null,
      longitude: (json['longitude'] is num)
          ? (json['longitude'] as num).toDouble()
          : null,
    );
  }
}

class AgentWorkflowResponse {
  final String route;
  final bool isEmergency;
  final String severity;
  final String facilityType;
  final String guidance;
  final String generalInfo;
  final String callScript;
  final String triageReason;
  final List<AgentFacility> facilities;

  AgentWorkflowResponse({
    required this.route,
    required this.isEmergency,
    required this.severity,
    required this.facilityType,
    required this.guidance,
    required this.generalInfo,
    required this.callScript,
    required this.triageReason,
    required this.facilities,
  });

  factory AgentWorkflowResponse.fromJson(Map<String, dynamic> json) {
    final rawFacilities = (json['facilities'] is List)
        ? json['facilities'] as List<dynamic>
        : const [];
    return AgentWorkflowResponse(
      route: (json['route'] ?? 'general_info').toString(),
      isEmergency: json['is_emergency'] == true,
      severity: (json['severity'] ?? 'none').toString(),
      facilityType: (json['facility_type'] ?? 'none').toString(),
      guidance: (json['guidance'] ?? '').toString(),
      generalInfo: (json['general_info'] ?? '').toString(),
      callScript: (json['call_script'] ?? '').toString(),
      triageReason: (json['triage_reason'] ?? '').toString(),
      facilities: rawFacilities
          .whereType<Map<String, dynamic>>()
          .map((e) => AgentFacility.fromJson(e))
          .toList(),
    );
  }
}

class FacilitySearchResponse {
  final List<dynamic> facilities;
  final int total;

  FacilitySearchResponse({
    required this.facilities,
    required this.total,
  });

  factory FacilitySearchResponse.fromJson(Map<String, dynamic> json) {
    return FacilitySearchResponse(
      facilities: json['facilities'] ?? [],
      total: json['total'] ?? 0,
    );
  }
}

class ApiService {
  // !!! IMPORTANT: Replace with your Flask API's actual IP address and port !!!
  // If running Flask locally and testing on an emulator:
  // - Android Emulator: usually 'http://10.0.2.2:5000'
  // - iOS Simulator: usually 'http://localhost:5000' or 'http://127.0.0.1:5000'
  // If testing on a physical device, use your computer's network IP address:
  // e.g., 'http://192.168.1.100:5000'
  static const String _facilityBaseUrl = 'http://localhost:5002';
  static const String _agentWorkflowBaseUrl = 'http://localhost:5003';

  Future<AgentWorkflowResponse> runAgentWorkflow({
    required String scenario,
    String? userId,
    double? latitude,
    double? longitude,
  }) async {
    final Uri url = Uri.parse('$_agentWorkflowBaseUrl/agent_workflow');
    try {
      final response = await http
          .post(
            url,
            headers: {'Content-Type': 'application/json; charset=UTF-8'},
            body: jsonEncode({
              'scenario': scenario,
              if (userId != null && userId.isNotEmpty) 'user_id': userId,
              if (latitude != null) 'latitude': latitude,
              if (longitude != null) 'longitude': longitude,
            }),
          )
          .timeout(const Duration(seconds: 45));

      final responseBody = utf8.decode(response.bodyBytes);
      final data = jsonDecode(responseBody);

      if (response.statusCode == 200) {
        if (data is Map<String, dynamic>) {
          if (data.containsKey('error')) {
            throw Exception('API Error: ${data['error']}');
          }
          return AgentWorkflowResponse.fromJson(data);
        }
        throw Exception('Invalid response format from workflow API');
      }

      String errorMessage = responseBody;
      if (data is Map<String, dynamic> && data.containsKey('error')) {
        errorMessage = data['error'].toString();
      }
      throw Exception(
          'Workflow API failed. Status: ${response.statusCode}, Message: $errorMessage');
    } catch (e) {
      throw Exception('ไม่สามารถเชื่อมต่อ Agent Workflow ได้: ${e.toString()}');
    }
  }

  // Get guidance with structured response (guidance, severity, facility_type)
  Future<GuidanceResponse> getGuidanceFromSentence(String sentence) async {
    // Backward-compatible helper mapped from the new single workflow endpoint.
    final workflow = await runAgentWorkflow(scenario: sentence);
    if (!workflow.isEmergency || workflow.route == 'general_info') {
      return GuidanceResponse(
        guidance: workflow.generalInfo,
        severity: 'none',
        facilityType: 'none',
      );
    }
    return GuidanceResponse(
      guidance: workflow.guidance,
      severity: workflow.severity == 'moderate' ? 'mild' : workflow.severity,
      facilityType: workflow.facilityType,
    );
  }

  // Find nearby medical facilities
  Future<FacilitySearchResponse> findNearbyFacilities({
    required double latitude,
    required double longitude,
    required String facilityType,
    required String severity,
  }) async {
    final Uri url = Uri.parse('$_facilityBaseUrl/find_facilities');
    try {
      final response = await http
          .post(
            url,
            headers: {'Content-Type': 'application/json; charset=UTF-8'},
            body: jsonEncode({
              'latitude': latitude,
              'longitude': longitude,
              'facility_type': facilityType,
              'severity': severity,
            }),
          )
          .timeout(const Duration(seconds: 30));

      if (response.statusCode == 200) {
        final responseBody = utf8.decode(response.bodyBytes);
        final data = jsonDecode(responseBody);

        if (data.containsKey('error')) {
          throw Exception('API Error: ${data['error']}');
        }

        return FacilitySearchResponse.fromJson(data);
      } else {
        // Attempt to decode error message if available
        String errorMessage = response.body;
        try {
          final errorData = jsonDecode(utf8.decode(response.bodyBytes));
          if (errorData.containsKey('error')) {
            errorMessage = errorData['error'];
          }
        } catch (_) {
          // Keep original body if not JSON
        }
        throw Exception(
            'Failed to find facilities. Status: ${response.statusCode}, Message: $errorMessage');
      }
    } catch (e) {
      print('ApiService Error (findNearbyFacilities): $e');
      throw Exception('ไม่สามารถค้นหาสถานพยาบาลได้: ${e.toString()}');
    }
  }
}
