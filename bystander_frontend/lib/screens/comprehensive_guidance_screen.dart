import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:bystander_frontend/services/tts_service.dart';

// Data model for emergency services (can be moved to a models folder)
class EmergencyService {
  final String name;
  final String phone;
  final IconData icon;
  EmergencyService({required this.name, required this.phone, required this.icon});
}

class ComprehensiveGuidanceScreen extends StatefulWidget {
  final String guidanceText;
  final String originalQuery;

  const ComprehensiveGuidanceScreen({
    super.key,
    required this.guidanceText,
    required this.originalQuery,
  });

  @override
  State<ComprehensiveGuidanceScreen> createState() => _ComprehensiveGuidanceScreenState();
}

class _ComprehensiveGuidanceScreenState extends State<ComprehensiveGuidanceScreen> {
  final ScrollController _scrollController = ScrollController();
  int _currentSectionIndex = 0; // 0: Guidance, 1: Nearby, 2: Call Script
  final TtsService _ttsService = TtsService();
  bool _isSpeaking = false;

  // GlobalKeys to identify sections for scrolling
  final GlobalKey _guidanceKey = GlobalKey();
  final GlobalKey _nearbyServicesKey = GlobalKey();
  final GlobalKey _callScriptKey = GlobalKey();

  final List<EmergencyService> _emergencyServices = [
    EmergencyService(name: 'สถาบันการแพทย์ฉุกเฉินแห่งชาติ', phone: '1669', icon: Icons.emergency_outlined),
    EmergencyService(name: 'เหตุด่วนเหตุร้าย (ตำรวจ)', phone: '191', icon: Icons.local_police_outlined),
    EmergencyService(name: 'ดับเพลิงและกู้ภัย', phone: '199', icon: Icons.fire_truck_outlined),
    EmergencyService(name: 'โรงพยาบาลตำรวจ (ตัวอย่าง)', phone: '022076000', icon: Icons.local_hospital_outlined),
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

  List<String> _parseSteps(String text) {
    final lines = text.split(RegExp(r'\n(?=\d+\.\s)|(?<=\.)\n-|(?<=\.)\s*\n\s*(?=[A-Za-z])'));
    return lines.map((line) => line.trim()).where((line) => line.isNotEmpty).toList();
  }

  Future<void> _makePhoneCall(String phoneNumber) async {
    final Uri launchUri = Uri(scheme: 'tel', path: phoneNumber);
    if (await canLaunchUrl(launchUri)) {
      await launchUrl(launchUri);
    } else {
      print('Could not launch $phoneNumber');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('ไม่สามารถโทรออกไปยัง $phoneNumber ได้')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final List<String> guidanceSteps = _parseSteps(widget.guidanceText);
    final TextTheme appTextTheme = Theme.of(context).textTheme;
    final ColorScheme appColorScheme = Theme.of(context).colorScheme;

  Future<void> readGuidanceAloud() async {
    if (_isSpeaking) {
      // If already speaking, stop it
      await _ttsService.stop();
      setState(() {
        _isSpeaking = false;
      });
      return;
    }

    if (guidanceSteps.isNotEmpty) {
      String allSteps = guidanceSteps.join('. ');
      setState(() {
        _isSpeaking = true;
      });
      await _ttsService.speak(allSteps);
      // Update state after a short delay to reflect speaking status
      Future.delayed(const Duration(milliseconds: 100), () {
        if (mounted) {
          setState(() {
            _isSpeaking = _ttsService.isSpeaking;
          });
        }
      });
    } else if (widget.guidanceText.isNotEmpty) {
      // Fallback to full text if steps parsing failed
      setState(() {
        _isSpeaking = true;
      });
      await _ttsService.speak(widget.guidanceText);
      Future.delayed(const Duration(milliseconds: 100), () {
        if (mounted) {
          setState(() {
            _isSpeaking = _ttsService.isSpeaking;
          });
        }
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
        padding: const EdgeInsets.symmetric(horizontal:16.0, vertical: 8.0), // Adjusted padding
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            _buildSectionTitle('สถานการณ์: ${widget.originalQuery}', key: null, isQuery: true, context: context), 
            const SizedBox(height: 8),
            const Divider(),
            _buildSectionTitle('คำแนะนำตามลำดับขั้นตอน:', key: _guidanceKey, context: context),
            if (guidanceSteps.isNotEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 8.0, horizontal: 16.0),
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
                        backgroundColor: _isSpeaking 
                            ? appColorScheme.primary 
                            : null,
                      ),
                    ),
                  ],
                ),
              ),

            // Second part: Displaying guidance steps or fallback text
            if (guidanceSteps.isNotEmpty) // Changed condition: now handles 1 or more steps
              Card(
                // CardTheme from your main.dart will style this Card.
                // You can add specific margin here if needed, e.g.:
                // margin: const EdgeInsets.symmetric(vertical: 8.0, horizontal: 16.0),
                child: Padding(
                  padding: const EdgeInsets.all(16.0), // Inner padding for the content within the card
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start, // Align text to the start (left for LTR)
                    mainAxisSize: MainAxisSize.min, // Ensure Column takes only necessary vertical space
                    children: List.generate(guidanceSteps.length, (index) {
                      return Padding(
                        // Add some vertical spacing between the text of different steps
                        padding: EdgeInsets.only(bottom: index < guidanceSteps.length - 1 ? 10.0 : 0.0),
                        child: Text(
                          guidanceSteps[index], // Display the guidance step text directly
                          style: appTextTheme.bodyLarge, // Apply your desired text style
                        ),
                      );
                    }),
                  ),
                ),
              )
            else // This else now correctly triggers only if guidanceSteps IS empty
              Card(
                // margin: const EdgeInsets.symmetric(vertical: 8.0, horizontal: 16.0), // Optional margin
                child: Padding(
                  padding: const EdgeInsets.all(16.0), // Padding for the fallback text
                  child: Text(
                    // Using widget.guidanceText if guidanceSteps is empty,
                    // or a default "not found" message if widget.guidanceText is also empty.
                    widget.guidanceText.isEmpty ? "ไม่พบคำแนะนำ" : widget.guidanceText,
                    style: appTextTheme.bodyLarge,
                    textAlign: TextAlign.justify, // Justified text alignment for the fallback
                  ),
                ),
              ),
              
            const SizedBox(height: 16),
            const Divider(),

            _buildSectionTitle('สถานบริการฉุกเฉิน (ตัวอย่าง)', key: _nearbyServicesKey, context: context),
            _buildNearbyServicesSection(context),
            const SizedBox(height: 16),
            const Divider(),

            _buildSectionTitle('แนะนำบทสนทนาเมื่อคุณโทรศัพท์', key: _callScriptKey, context: context),
            _buildCallScriptSection(context),
            const SizedBox(height: 16),
             Center(
              child: Column(
                children: [
                  Text(
                    'หากยังมีคำถามอยู่ หรือต้องการความช่วยเหลือเพิ่มเติม:',
                     style: appTextTheme.bodyMedium?.copyWith(color: appTextTheme.bodyMedium?.color?.withOpacity(0.8)),
                     textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 15),
                  Icon(Icons.mic, size: 40, color: appColorScheme.primary),
                  const SizedBox(height: 5),
                   Text(
                    'กดค้างแล้วพูดได้เลย (ฟังก์ชันนี้จะพัฒนาในอนาคต)',
                    style: appTextTheme.bodySmall?.copyWith(color: appTextTheme.bodySmall?.color?.withOpacity(0.7)),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 60), 
          ],
        ),
      ),
      bottomNavigationBar: BottomNavigationBar( // Theme applied from main.dart
        items: const <BottomNavigationBarItem>[
          BottomNavigationBarItem(icon: Icon(Icons.lightbulb_outline), label: 'คำแนะนำ'),
          BottomNavigationBarItem(icon: Icon(Icons.map_outlined), label: 'ใกล้ฉัน'),
          BottomNavigationBarItem(icon: Icon(Icons.phone_in_talk_outlined), label: 'บทสนทนา'),
        ],
        currentIndex: _currentSectionIndex,
        onTap: _scrollToSection,
        type: BottomNavigationBarType.fixed,
      ),
    );
  }

  Widget _buildSectionTitle(String title, {required GlobalKey? key, bool isQuery = false, required BuildContext context}) {
    final TextTheme appTextTheme = Theme.of(context).textTheme;
    final ColorScheme appColorScheme = Theme.of(context).colorScheme;
    return Padding(
      key: key,
      padding: const EdgeInsets.only(top: 12.0, bottom: 8.0), // Adjusted padding
      child: Text(
        title,
        style: (isQuery ? appTextTheme.titleMedium : appTextTheme.titleLarge)?.copyWith(
          fontWeight: FontWeight.bold,
          color: isQuery ? appColorScheme.primary.withOpacity(0.85) : appColorScheme.primary,
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
            title: Text(service.name, style: appTextTheme.titleSmall?.copyWith(fontWeight: FontWeight.w600)),
            subtitle: Text('โทร: ${service.phone}', style: appTextTheme.bodyMedium),
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
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _buildScriptPoint("ผู้แจ้ง:", "สวัสดีครับ/ค่ะ ต้องการแจ้งเหตุฉุกเฉินครับ/ค่ะ", context),
            _buildScriptPoint("สถานการณ์:", "(อธิบายสั้นๆ ว่าเกิดอะไรขึ้น เช่น 'มีคนหมดสติ', 'เกิดอุบัติเหตุรถชน')", context),
            _buildScriptPoint("สถานที่:", "อยู่ที่ (บอกตำแหน่งที่เกิดเหตุให้ชัดเจนที่สุด เช่น 'หน้าอาคาร A ถนน B ใกล้กับ C')", context),
            _buildScriptPoint("ผู้บาดเจ็บ/ผู้ป่วย:", "(บอกจำนวนคน อาการเบื้องต้นที่เห็น เช่น 'มีผู้บาดเจ็บ 1 คน ไม่รู้สึกตัว', 'มีเลือดออกมาก')", context),
            _buildScriptPoint("ชื่อผู้แจ้ง:", "ผม/ดิฉันชื่อ (ชื่อของคุณ)", context),
            _buildScriptPoint("เบอร์ติดต่อกลับ:", "เบอร์โทรศัพท์ (เบอร์ของคุณ)", context),
            _buildScriptPoint("ความช่วยเหลือที่ทำไปแล้ว:", "(ถ้ามีการปฐมพยาบาลเบื้องต้นไปแล้ว ให้แจ้งด้วย)", context),
            _buildScriptPoint("คำถามเพิ่มเติม:", "มีอะไรที่ผม/ดิฉันควรทำเพิ่มเติมระหว่างรอเจ้าหน้าที่ไหมครับ/คะ?", context),
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
            TextSpan(text: '$title ', style: TextStyle(fontWeight: FontWeight.bold, color: appColorScheme.primary)),
            TextSpan(text: content), // Inherits style from appTextTheme.bodyLarge
          ],
        ),
      ),
    );
  }
}