import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:url_launcher/url_launcher.dart';
import 'package:bystander_frontend/screens/facility_finder_screen.dart';
import 'package:bystander_frontend/services/tts_service.dart';
import 'package:bystander_frontend/services/api_service.dart';

// Data model for emergency services (can be moved to a models folder)
class EmergencyService {
  final String name;
  final String phone;
  final IconData icon;
  EmergencyService(
      {required this.name, required this.phone, required this.icon});
}

class ComprehensiveGuidanceScreen extends StatefulWidget {
  final String guidanceText;
  final String originalQuery;
  final String severity;
  final String facilityType;
  final List<AgentFacility> facilities;
  final String callScript;
  final double? userLatitude;
  final double? userLongitude;

  const ComprehensiveGuidanceScreen({
    super.key,
    required this.guidanceText,
    required this.originalQuery,
    required this.severity,
    required this.facilityType,
    this.facilities = const [],
    this.callScript = '',
    this.userLatitude,
    this.userLongitude,
  });

  @override
  State<ComprehensiveGuidanceScreen> createState() =>
      _ComprehensiveGuidanceScreenState();
}

class _ComprehensiveGuidanceScreenState
    extends State<ComprehensiveGuidanceScreen> {
  static const double _fallbackLatitude = 13.7563;
  static const double _fallbackLongitude = 100.5018;
  final ScrollController _scrollController = ScrollController();
  int _currentSectionIndex = 0; // 0: Guidance, 1: Nearby, 2: Call Script
  final TtsService _ttsService = TtsService();
  bool _isSpeaking = false;
  List<Map<String, dynamic>> _videoRules = [];
  String? _matchedVideoUrl;
  String? _matchedVideoKeyword;

  // GlobalKeys to identify sections for scrolling
  final GlobalKey _guidanceKey = GlobalKey();
  final GlobalKey _nearbyServicesKey = GlobalKey();
  final GlobalKey _callScriptKey = GlobalKey();

  final List<EmergencyService> _emergencyServices = [
    EmergencyService(
        name: 'สถาบันการแพทย์ฉุกเฉินแห่งชาติ',
        phone: '1669',
        icon: Icons.emergency_outlined),
    EmergencyService(
        name: 'เหตุด่วนเหตุร้าย (ตำรวจ)',
        phone: '191',
        icon: Icons.local_police_outlined),
    EmergencyService(
        name: 'ดับเพลิงและกู้ภัย',
        phone: '199',
        icon: Icons.fire_truck_outlined),
    EmergencyService(
        name: 'โรงพยาบาลตำรวจ (ตัวอย่าง)',
        phone: '022076000',
        icon: Icons.local_hospital_outlined),
  ];

  @override
  void dispose() {
    _scrollController.dispose();
    _ttsService.stop();
    super.dispose();
  }

  @override
  void initState() {
    super.initState();
    _ttsService.initialize();
    _loadVideoRules();
  }

  Future<void> _loadVideoRules() async {
    try {
      final raw = await rootBundle.loadString('assets/video_instructions.json');
      final payload = jsonDecode(raw);
      final items = (payload['items'] as List<dynamic>? ?? [])
          .whereType<Map<String, dynamic>>()
          .toList();
      if (!mounted) return;
      setState(() {
        _videoRules = items;
      });
      _matchVideoFromGuidance();
    } catch (_) {
      // Optional feature: fail silently if asset missing.
    }
  }

  void _matchVideoFromGuidance() {
    final guidanceLower = widget.guidanceText.toLowerCase();
    for (final row in _videoRules) {
      final keywords = (row['keywords'] as List<dynamic>? ?? [])
          .map((e) => e.toString().trim())
          .where((e) => e.isNotEmpty)
          .toList();
      final video = (row['video'] ?? '').toString().trim();
      if (video.isEmpty) continue;
      for (final kw in keywords) {
        if (guidanceLower.contains(kw.toLowerCase())) {
          if (!mounted) return;
          setState(() {
            _matchedVideoUrl = video;
            _matchedVideoKeyword = kw;
          });
          return;
        }
      }
    }
  }

  Future<void> _openVideoInstruction() async {
    final url = _matchedVideoUrl;
    if (url == null || url.trim().isEmpty) return;
    final uri = Uri.parse(url);
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
  }

  void _scrollToSection(int index) {
    GlobalKey key;
    switch (index) {
      case 0:
        key = _guidanceKey;
        break;
      case 1:
        key = _nearbyServicesKey;
        break;
      case 2:
        key = _callScriptKey;
        break;
      default:
        return;
    }
    final context = key.currentContext;
    if (context != null) {
      Scrollable.ensureVisible(
        context,
        duration: const Duration(milliseconds: 500),
        curve: Curves.easeInOut,
        alignment: 0.0,
      );
      setState(() {
        _currentSectionIndex = index;
      });
    }
  }

  String _extractGuidanceIntro(String text) {
    final normalized = text.replaceAll('\r', '').trim();
    final firstStepMatch = RegExp(r'\d+[\.\)]\s+').firstMatch(normalized);
    if (firstStepMatch == null || firstStepMatch.start == 0) {
      return '';
    }
    return normalized.substring(0, firstStepMatch.start).trim();
  }

  List<String> _parseGuidanceSteps(String text) {
    final normalized = text.replaceAll('\r', ' ').replaceAll('\n', ' ').trim();
    if (normalized.isEmpty) return [];

    final hasNumberedSteps = RegExp(r'\d+[\.\)]\s+').hasMatch(normalized);
    if (!hasNumberedSteps) {
      return normalized
          .split(RegExp(r'[•\-]\s+|\.\s+(?=[ก-๙A-Za-z])'))
          .map((e) => e.trim())
          .where((e) => e.isNotEmpty)
          .toList();
    }

    final parts = normalized
        .split(RegExp(r'(?=\d+[\.\)]\s+)'))
        .map((e) => e.trim())
        .where((e) => e.isNotEmpty)
        .map((e) => e.replaceFirst(RegExp(r'^\d+[\.\)]\s*'), '').trim())
        .where((e) => e.isNotEmpty)
        .toList();
    return parts;
  }

  Future<void> _openNearbyFacilitiesMap() async {
    final mapped = widget.facilities
        .map(
          (f) => Facility(
            placeId: '${f.latitude ?? 0}_${f.longitude ?? 0}_${f.name}',
            name: f.name,
            address: f.address,
            latitude: f.latitude ?? 0,
            longitude: f.longitude ?? 0,
            rating: f.rating,
            userRatingsTotal: 0,
            openNow: null,
            phoneNumber: f.phoneNumber,
            website: '',
            types: const [],
          ),
        )
        .where((f) => f.latitude != 0 || f.longitude != 0)
        .toList();

    final hasUserLocation =
        widget.userLatitude != null && widget.userLongitude != null;

    final centerLat = hasUserLocation
        ? widget.userLatitude!
        : (mapped.isNotEmpty ? mapped.first.latitude : _fallbackLatitude);
    final centerLon = hasUserLocation
        ? widget.userLongitude!
        : (mapped.isNotEmpty ? mapped.first.longitude : _fallbackLongitude);

    if (!mounted) return;
    if (!hasUserLocation && mapped.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('ไม่พบพิกัดตำแหน่งผู้ใช้ จึงใช้จุดกึ่งกลางเริ่มต้น'),
        ),
      );
    }
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (context) => FacilityFinderScreen(
          facilities: mapped,
          userLatitude: centerLat,
          userLongitude: centerLon,
          facilityType: widget.facilityType,
          severity: widget.severity,
        ),
      ),
    );
  }

  Future<void> _makePhoneCall(String phoneNumber) async {
    final Uri launchUri = Uri(scheme: 'tel', path: phoneNumber);
    if (await canLaunchUrl(launchUri)) {
      await launchUrl(launchUri);
    } else {
      debugPrint('Could not launch $phoneNumber');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('ไม่สามารถโทรออกไปยัง $phoneNumber ได้')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final String guidanceIntro = _extractGuidanceIntro(widget.guidanceText);
    final List<String> guidanceSteps = _parseGuidanceSteps(widget.guidanceText);
    final TextTheme appTextTheme = Theme.of(context).textTheme;
    final ColorScheme appColorScheme = Theme.of(context).colorScheme;
    final bool isCritical = widget.severity.toLowerCase() == 'critical';
    final Color urgencyColor =
        isCritical ? const Color(0xFFB42318) : const Color(0xFF1E6A52);

    Future<void> readGuidanceAloud() async {
      if (_isSpeaking) {
        // If already speaking, stop it
        await _ttsService.stop();
        setState(() {
          _isSpeaking = false;
        });
        return;
      }

      try {
        if (guidanceSteps.isNotEmpty) {
          String allSteps = guidanceSteps.join('. ');
          setState(() {
            _isSpeaking = true;
          });
          await _ttsService.speak(allSteps);
        } else if (widget.guidanceText.isNotEmpty) {
          // Fallback to full text if steps parsing failed
          setState(() {
            _isSpeaking = true;
          });
          await _ttsService.speak(widget.guidanceText);
        }

        Future.delayed(const Duration(milliseconds: 100), () {
          if (mounted) {
            setState(() {
              _isSpeaking = _ttsService.isSpeaking;
            });
          }
        });
      } catch (e) {
        if (!mounted) return;
        ScaffoldMessenger.of(this.context).showSnackBar(
          SnackBar(content: Text('ไม่สามารถอ่านออกเสียงได้: ${e.toString()}')),
        );
        setState(() {
          _isSpeaking = false;
        });
      }
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('ข้อมูลช่วยเหลือฉุกเฉิน'),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => Navigator.of(context).pop(),
        ),
      ),
      body: SingleChildScrollView(
        controller: _scrollController,
        padding: const EdgeInsets.symmetric(
            horizontal: 16.0, vertical: 8.0), // Adjusted padding
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Container(
              width: double.infinity,
              margin: const EdgeInsets.only(top: 6, bottom: 12),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: isCritical
                    ? const Color(0xFFFDECEA)
                    : const Color(0xFFEAF7F1),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: urgencyColor.withValues(alpha: 0.45)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      Icon(
                        isCritical
                            ? Icons.warning_amber_rounded
                            : Icons.verified_user_outlined,
                        color: urgencyColor,
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          isCritical
                              ? 'เคสวิกฤต: ให้โทร 1669 และทำตามขั้นตอนทันที'
                              : 'เคสเร่งด่วนปานกลาง: ทำตามขั้นตอนและติดตามอาการ',
                          style: appTextTheme.titleSmall?.copyWith(
                            fontWeight: FontWeight.w700,
                            color: urgencyColor,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 10),
                  ElevatedButton.icon(
                    onPressed: () => _makePhoneCall('1669'),
                    icon: const Icon(Icons.call),
                    label: const Text('โทร 1669 ตอนนี้'),
                    style: ElevatedButton.styleFrom(
                      minimumSize: const Size(double.infinity, 48),
                      backgroundColor: urgencyColor,
                      foregroundColor: Colors.white,
                    ),
                  ),
                ],
              ),
            ),
            _buildSectionTitle('สถานการณ์: ${widget.originalQuery}',
                key: null, isQuery: true, context: context),
            const SizedBox(height: 8),
            const Divider(),
            _buildSectionTitle('คำแนะนำตามลำดับขั้นตอน:',
                key: _guidanceKey, context: context),
            if (widget.guidanceText.trim().isNotEmpty)
              Padding(
                padding:
                    const EdgeInsets.symmetric(vertical: 8.0, horizontal: 16.0),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    ElevatedButton.icon(
                      onPressed: readGuidanceAloud,
                      icon: Icon(
                        _isSpeaking ? Icons.stop : Icons.volume_up,
                        color: _isSpeaking ? Colors.white : Colors.red,
                      ),
                      label: Text(_isSpeaking ? 'หยุด' : 'อ่านออกเสียง'),
                      style: ElevatedButton.styleFrom(
                        backgroundColor:
                            _isSpeaking ? appColorScheme.primary : null,
                      ),
                    ),
                  ],
                ),
              ),
            if (guidanceIntro.isNotEmpty)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Text(
                    guidanceIntro,
                    style: appTextTheme.bodyLarge?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ),
            if (guidanceSteps.isNotEmpty)
              ...List.generate(guidanceSteps.length, (index) {
                return Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: Container(
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(
                        color: appColorScheme.primary.withValues(alpha: 0.15),
                      ),
                      boxShadow: [
                        BoxShadow(
                          color: Colors.black.withValues(alpha: 0.04),
                          blurRadius: 8,
                          offset: const Offset(0, 3),
                        ),
                      ],
                    ),
                    child: Padding(
                      padding: const EdgeInsets.all(14),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          CircleAvatar(
                            radius: 16,
                            backgroundColor: appColorScheme.primary,
                            child: Text(
                              '${index + 1}',
                              style: const TextStyle(
                                color: Colors.white,
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Text(
                              guidanceSteps[index],
                              style: appTextTheme.titleMedium?.copyWith(
                                height: 1.45,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                );
              })
            else
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Text(
                    widget.guidanceText.isEmpty
                        ? 'ไม่พบคำแนะนำ'
                        : widget.guidanceText,
                    style: appTextTheme.bodyLarge,
                  ),
                ),
              ),
            if (_matchedVideoUrl != null) ...[
              const SizedBox(height: 8),
              Card(
                child: ListTile(
                  leading:
                      Icon(Icons.smart_display, color: appColorScheme.primary),
                  title: const Text('วิดีโอสาธิตการปฐมพยาบาล'),
                  subtitle: Text(
                    _matchedVideoKeyword == null
                        ? 'กดเพื่อเปิดวิดีโอ'
                        : 'พบคำแนะนำเกี่ยวกับ: $_matchedVideoKeyword',
                  ),
                  trailing: const Icon(Icons.open_in_new),
                  onTap: _openVideoInstruction,
                ),
              ),
            ],
            const SizedBox(height: 16),
            const Divider(),
            _buildSectionTitle('เบอร์ฉุกเฉินและสถานพยาบาล',
                key: _nearbyServicesKey, context: context),
            _buildNearbyServicesSection(context),
            const SizedBox(height: 8),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8),
              child: ElevatedButton.icon(
                onPressed: _openNearbyFacilitiesMap,
                icon: const Icon(Icons.map_outlined),
                label: const Text('ค้นหาสถานพยาบาลใกล้เคียงบนแผนที่'),
                style: ElevatedButton.styleFrom(
                  minimumSize: const Size(double.infinity, 48),
                ),
              ),
            ),
            const SizedBox(height: 16),
            const Divider(),
            _buildSectionTitle('แนะนำบทสนทนาเมื่อคุณโทรศัพท์',
                key: _callScriptKey, context: context),
            _buildCallScriptSection(context),
            const SizedBox(height: 16),
            Center(
              child: Column(
                children: [
                  Text(
                    'หากยังมีคำถามอยู่ หรือต้องการความช่วยเหลือเพิ่มเติม:',
                    style: appTextTheme.bodyMedium?.copyWith(
                        color: appTextTheme.bodyMedium?.color
                            ?.withValues(alpha: 0.8)),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 15),
                  Icon(Icons.mic, size: 40, color: appColorScheme.primary),
                  const SizedBox(height: 5),
                  Text(
                    'กดค้างแล้วพูดได้เลย (ฟังก์ชันนี้จะพัฒนาในอนาคต)',
                    style: appTextTheme.bodySmall?.copyWith(
                        color: appTextTheme.bodySmall?.color
                            ?.withValues(alpha: 0.7)),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 60),
          ],
        ),
      ),
      bottomNavigationBar: BottomNavigationBar(
        // Theme applied from main.dart
        items: const <BottomNavigationBarItem>[
          BottomNavigationBarItem(
              icon: Icon(Icons.lightbulb_outline), label: 'คำแนะนำ'),
          BottomNavigationBarItem(
              icon: Icon(Icons.map_outlined), label: 'ใกล้ฉัน'),
          BottomNavigationBarItem(
              icon: Icon(Icons.phone_in_talk_outlined), label: 'บทสนทนา'),
        ],
        currentIndex: _currentSectionIndex,
        onTap: _scrollToSection,
        type: BottomNavigationBarType.fixed,
      ),
    );
  }

  Widget _buildSectionTitle(String title,
      {required GlobalKey? key,
      bool isQuery = false,
      required BuildContext context}) {
    final TextTheme appTextTheme = Theme.of(context).textTheme;
    final ColorScheme appColorScheme = Theme.of(context).colorScheme;
    return Padding(
      key: key,
      padding:
          const EdgeInsets.only(top: 12.0, bottom: 8.0), // Adjusted padding
      child: Text(
        title,
        style: (isQuery ? appTextTheme.titleMedium : appTextTheme.titleLarge)
            ?.copyWith(
          fontWeight: FontWeight.bold,
          color: isQuery
              ? appColorScheme.primary.withValues(alpha: 0.85)
              : appColorScheme.primary,
        ),
      ),
    );
  }

  Widget _buildNearbyServicesSection(BuildContext context) {
    final TextTheme appTextTheme = Theme.of(context).textTheme;
    final ColorScheme appColorScheme = Theme.of(context).colorScheme;
    return ListView.builder(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      itemCount: _emergencyServices.length,
      itemBuilder: (context, index) {
        final service = _emergencyServices[index];
        return Card(
          child: ListTile(
            leading: CircleAvatar(
              backgroundColor: appColorScheme.primary,
              child: Icon(service.icon, color: appColorScheme.onPrimary),
            ),
            title: Text(service.name,
                style: appTextTheme.titleSmall
                    ?.copyWith(fontWeight: FontWeight.w600)),
            subtitle:
                Text('โทร: ${service.phone}', style: appTextTheme.bodyMedium),
            trailing: IconButton(
              icon: Icon(Icons.call, color: appColorScheme.primary),
              onPressed: () => _makePhoneCall(service.phone),
            ),
            onTap: () => _makePhoneCall(service.phone),
          ),
        );
      },
    );
  }

  Widget _buildCallScriptSection(BuildContext context) {
    if (widget.callScript.trim().isNotEmpty) {
      final lines = widget.callScript
          .split('\n')
          .map((e) => e.trim())
          .where((e) => e.isNotEmpty)
          .toList();
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(16.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: lines
                .map((line) => Padding(
                      padding: const EdgeInsets.symmetric(vertical: 6),
                      child: Text(line),
                    ))
                .toList(),
          ),
        ),
      );
    }

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _buildScriptPoint("ผู้แจ้ง:",
                "สวัสดีครับ/ค่ะ ต้องการแจ้งเหตุฉุกเฉินครับ/ค่ะ", context),
            _buildScriptPoint(
                "สถานการณ์:",
                "(อธิบายสั้นๆ ว่าเกิดอะไรขึ้น เช่น 'มีคนหมดสติ', 'เกิดอุบัติเหตุรถชน')",
                context),
            _buildScriptPoint(
                "สถานที่:",
                "อยู่ที่ (บอกตำแหน่งที่เกิดเหตุให้ชัดเจนที่สุด เช่น 'หน้าอาคาร A ถนน B ใกล้กับ C')",
                context),
            _buildScriptPoint(
                "ผู้บาดเจ็บ/ผู้ป่วย:",
                "(บอกจำนวนคน อาการเบื้องต้นที่เห็น เช่น 'มีผู้บาดเจ็บ 1 คน ไม่รู้สึกตัว', 'มีเลือดออกมาก')",
                context),
            _buildScriptPoint(
                "ชื่อผู้แจ้ง:", "ผม/ดิฉันชื่อ (ชื่อของคุณ)", context),
            _buildScriptPoint(
                "เบอร์ติดต่อกลับ:", "เบอร์โทรศัพท์ (เบอร์ของคุณ)", context),
            _buildScriptPoint("ความช่วยเหลือที่ทำไปแล้ว:",
                "(ถ้ามีการปฐมพยาบาลเบื้องต้นไปแล้ว ให้แจ้งด้วย)", context),
            _buildScriptPoint(
                "คำถามเพิ่มเติม:",
                "มีอะไรที่ผม/ดิฉันควรทำเพิ่มเติมระหว่างรอเจ้าหน้าที่ไหมครับ/คะ?",
                context),
          ],
        ),
      ),
    );
  }

  Widget _buildScriptPoint(String title, String content, BuildContext context) {
    final TextTheme appTextTheme = Theme.of(context).textTheme;
    final ColorScheme appColorScheme = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8.0),
      child: RichText(
        text: TextSpan(
          style: appTextTheme.bodyLarge, // Default style for this RichText
          children: <TextSpan>[
            TextSpan(
                text: '$title ',
                style: TextStyle(
                    fontWeight: FontWeight.bold,
                    color: appColorScheme.primary)),
            TextSpan(
                text: content), // Inherits style from appTextTheme.bodyLarge
          ],
        ),
      ),
    );
  }
}
