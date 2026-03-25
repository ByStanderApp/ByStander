import 'dart:convert';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:http/http.dart' as http;
import 'package:bystander_frontend/services/app_config.dart';

Map<String, dynamic> buildAgentWorkflowPayload({
  required String scenario,
  String? userId,
  String? callerUserId,
  String? targetUserId,
  double? latitude,
  double? longitude,
  Map<String, dynamic>? medicalContext,
}) {
  return {
    'scenario': scenario,
    if (callerUserId != null && callerUserId.isNotEmpty)
      'caller_user_id': callerUserId,
    if (targetUserId != null && targetUserId.isNotEmpty)
      'target_user_id': targetUserId,
    if (userId != null && userId.isNotEmpty) 'user_id': userId,
    if (latitude != null) 'latitude': latitude,
    if (longitude != null) 'longitude': longitude,
    if (medicalContext != null && medicalContext.isNotEmpty)
      'medical_context': medicalContext,
  };
}

Map<String, dynamic> buildFindFacilitiesPayload({
  required String scenario,
  String? severity,
  String? facilityType,
  double? latitude,
  double? longitude,
}) {
  return {
    'scenario': scenario,
    if (severity != null && severity.isNotEmpty) 'severity': severity,
    if (facilityType != null && facilityType.isNotEmpty)
      'facility_type': facilityType,
    if (latitude != null) 'latitude': latitude,
    if (longitude != null) 'longitude': longitude,
  };
}

Map<String, dynamic> buildCallScriptPayload({
  required String scenario,
  String? guidance,
  String? severity,
  String? facilityType,
  String? callerUserId,
  String? targetUserId,
  double? latitude,
  double? longitude,
  Map<String, dynamic>? medicalContext,
}) {
  return {
    'scenario': scenario,
    if (guidance != null && guidance.isNotEmpty) 'guidance': guidance,
    if (severity != null && severity.isNotEmpty) 'severity': severity,
    if (facilityType != null && facilityType.isNotEmpty)
      'facility_type': facilityType,
    if (callerUserId != null && callerUserId.isNotEmpty)
      'caller_user_id': callerUserId,
    if (targetUserId != null && targetUserId.isNotEmpty)
      'target_user_id': targetUserId,
    if (targetUserId != null && targetUserId.isNotEmpty)
      'user_id': targetUserId,
    if (latitude != null) 'latitude': latitude,
    if (longitude != null) 'longitude': longitude,
    if (medicalContext != null && medicalContext.isNotEmpty)
      'medical_context': medicalContext,
  };
}

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
  final List<AgentFacility> facilities;
  final int total;
  final bool pendingLocation;
  final String locationContext;

  FacilitySearchResponse({
    required this.facilities,
    required this.total,
    this.pendingLocation = false,
    this.locationContext = '',
  });

  factory FacilitySearchResponse.fromJson(Map<String, dynamic> json) {
    final rawFacilities = (json['facilities'] is List)
        ? json['facilities'] as List<dynamic>
        : const [];
    return FacilitySearchResponse(
      facilities: rawFacilities
          .whereType<Map<String, dynamic>>()
          .map((e) => AgentFacility.fromJson(e))
          .toList(),
      total: (json['total'] is num) ? (json['total'] as num).toInt() : 0,
      pendingLocation: json['pending_location'] == true,
      locationContext: (json['location_context'] ?? '').toString(),
    );
  }
}

class CallScriptResponse {
  final String callScript;
  final String locationContext;
  final List<AgentFacility> facilities;
  final List<String> usedMedicalHistory;

  CallScriptResponse({
    required this.callScript,
    required this.locationContext,
    required this.facilities,
    required this.usedMedicalHistory,
  });

  factory CallScriptResponse.fromJson(Map<String, dynamic> json) {
    final rawFacilities = (json['facilities'] is List)
        ? json['facilities'] as List<dynamic>
        : const [];
    final rawMedicalHistory = (json['used_medical_history'] is List)
        ? json['used_medical_history'] as List<dynamic>
        : const [];
    return CallScriptResponse(
      callScript: (json['call_script'] ?? '').toString(),
      locationContext: (json['location_context'] ?? '').toString(),
      facilities: rawFacilities
          .whereType<Map<String, dynamic>>()
          .map((e) => AgentFacility.fromJson(e))
          .toList(),
      usedMedicalHistory: rawMedicalHistory
          .map((e) => e.toString().trim())
          .where((e) => e.isNotEmpty)
          .toList(),
    );
  }
}

class ApiService {
  static final String _agentWorkflowBaseUrl = AppConfig.apiBaseUrl;
  static final String _facilityBaseUrl = _agentWorkflowBaseUrl;

  Future<Map<String, String>> _authHeaders() async {
    final user = FirebaseAuth.instance.currentUser;
    final token = await user?.getIdToken();
    return <String, String>{
      'Content-Type': 'application/json; charset=UTF-8',
      if (token != null && token.isNotEmpty) 'Authorization': 'Bearer $token',
    };
  }

  Future<AgentWorkflowResponse> runAgentWorkflow({
    required String scenario,
    String? userId,
    String? callerUserId,
    String? targetUserId,
    double? latitude,
    double? longitude,
    Map<String, dynamic>? medicalContext,
  }) async {
    final Uri url = Uri.parse('$_agentWorkflowBaseUrl/agent_workflow');
    final user = FirebaseAuth.instance.currentUser;

    final effectiveCaller = (callerUserId != null && callerUserId.isNotEmpty)
        ? callerUserId
        : user?.uid;
    final effectiveTarget = (targetUserId != null && targetUserId.isNotEmpty)
        ? targetUserId
        : (userId != null && userId.isNotEmpty)
            ? userId
            : user?.uid;

    try {
      final response = await http
          .post(
            url,
            headers: await _authHeaders(),
            body: jsonEncode(
              buildAgentWorkflowPayload(
                scenario: scenario,
                callerUserId: effectiveCaller,
                targetUserId: effectiveTarget,
                userId: effectiveTarget,
                latitude: latitude,
                longitude: longitude,
                medicalContext: medicalContext,
              ),
            ),
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

  Future<GuidanceResponse> getGuidanceFromSentence(String sentence) async {
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

  Future<FacilitySearchResponse> findNearbyFacilities({
    required String scenario,
    String? severity,
    String? facilityType,
    double? latitude,
    double? longitude,
  }) async {
    final Uri url = Uri.parse('$_facilityBaseUrl/find_facilities');
    try {
      final response = await http
          .post(
            url,
            headers: {'Content-Type': 'application/json; charset=UTF-8'},
            body: jsonEncode(
              buildFindFacilitiesPayload(
                scenario: scenario,
                severity: severity,
                facilityType: facilityType,
                latitude: latitude,
                longitude: longitude,
              ),
            ),
          )
          .timeout(const Duration(seconds: 30));

      final responseBody = utf8.decode(response.bodyBytes);
      final data = jsonDecode(responseBody);
      if (response.statusCode == 200 && data is Map<String, dynamic>) {
        if (data.containsKey('error')) {
          throw Exception('API Error: ${data['error']}');
        }
        return FacilitySearchResponse.fromJson(data);
      }
      throw Exception(
          'Failed to find facilities. Status: ${response.statusCode}, Message: $responseBody');
    } catch (e) {
      throw Exception('ไม่สามารถค้นหาสถานพยาบาลได้: ${e.toString()}');
    }
  }

  Future<CallScriptResponse> getCallScript({
    required String scenario,
    String? guidance,
    String? severity,
    String? facilityType,
    String? callerUserId,
    String? targetUserId,
    double? latitude,
    double? longitude,
    Map<String, dynamic>? medicalContext,
  }) async {
    final Uri url = Uri.parse('$_facilityBaseUrl/call_script');
    final user = FirebaseAuth.instance.currentUser;
    final effectiveCaller = (callerUserId != null && callerUserId.isNotEmpty)
        ? callerUserId
        : user?.uid;
    final effectiveTarget = (targetUserId != null && targetUserId.isNotEmpty)
        ? targetUserId
        : user?.uid;
    try {
      final response = await http
          .post(
            url,
            headers: await _authHeaders(),
            body: jsonEncode(
              buildCallScriptPayload(
                scenario: scenario,
                guidance: guidance,
                severity: severity,
                facilityType: facilityType,
                callerUserId: effectiveCaller,
                targetUserId: effectiveTarget,
                latitude: latitude,
                longitude: longitude,
                medicalContext: medicalContext,
              ),
            ),
          )
          .timeout(const Duration(seconds: 30));
      final responseBody = utf8.decode(response.bodyBytes);
      final data = jsonDecode(responseBody);
      if (response.statusCode == 200 && data is Map<String, dynamic>) {
        if (data.containsKey('error')) {
          throw Exception('API Error: ${data['error']}');
        }
        return CallScriptResponse.fromJson(data);
      }
      throw Exception(
          'Failed to get call script. Status: ${response.statusCode}, Message: $responseBody');
    } catch (e) {
      throw Exception('ไม่สามารถสร้างบทสนทนาโทรฉุกเฉินได้: ${e.toString()}');
    }
  }
}
