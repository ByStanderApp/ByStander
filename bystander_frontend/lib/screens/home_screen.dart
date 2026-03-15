import 'package:flutter/material.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;
import 'package:permission_handler/permission_handler.dart';
import 'package:bystander_frontend/services/api_service.dart';
import 'package:bystander_frontend/screens/comprehensive_guidance_screen.dart';
import 'package:bystander_frontend/screens/general_first_aid_screen.dart';
import 'package:bystander_frontend/screens/general_info_screen.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:geolocator/geolocator.dart';
import 'package:url_launcher/url_launcher.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  late stt.SpeechToText _speech;
  bool _isListening = false;
  String _voiceInputText = 'กดปุ่มไมโครโฟนค้างไว้ เพื่อพูด';
  String _status = '';
  final ApiService _apiService = ApiService();
  bool _isLoading = false;

  final TextEditingController _textEditingController = TextEditingController();
  final Color microphoneColor =
      Colors.redAccent; // User specified color for mic button
  final Color microphoneListeningColor =
      const Color(0xFF36536B); // User specified this for listening state

  @override
  void initState() {
    super.initState();
    _speech = stt.SpeechToText();
  }

  @override
  void dispose() {
    _textEditingController.dispose();
    _speech.cancel();
    super.dispose();
  }

  void _listen() async {
    var microphoneStatus = await Permission.microphone.request();
    if (microphoneStatus.isGranted) {
      if (!_isListening) {
        bool available = await _speech.initialize(onStatus: (val) {
          debugPrint('onStatus: $val');
          if (val == 'notListening' || val == 'done') {
            setState(() => _isListening = false);
            if (_voiceInputText.isNotEmpty &&
                _voiceInputText != 'กำลังฟัง...' &&
                _voiceInputText != 'กดปุ่มไมโครโฟนค้างไว้ เพื่อพูด') {
              _fetchGuidance(_voiceInputText);
            }
          }
        }, onError: (val) {
          debugPrint('onError: $val');
          setState(() {
            _isListening = false;
            _status = 'เกิดข้อผิดพลาดในการฟัง: ${val.errorMsg}';
          });
        });
        if (available) {
          setState(() => _isListening = true);
          _speech.listen(
            onResult: (val) => setState(() {
              _voiceInputText = val.recognizedWords;
              _textEditingController.text = val.recognizedWords;
              if (val.recognizedWords.isNotEmpty) _status = '';
            }),
            localeId: 'th_TH',
            listenFor: const Duration(seconds: 30),
            pauseFor: const Duration(seconds: 5),
          );
          setState(() {
            _voiceInputText = 'กำลังฟัง...';
            _textEditingController.clear();
            _status = '';
          });
        } else {
          setState(() {
            _status = "ไม่สามารถเข้าถึงไมโครโฟนได้";
            _isListening = false;
          });
        }
      }
    } else {
      setState(() => _status = 'ไม่ได้รับอนุญาตให้ใช้ไมโครโฟน');
    }
  }

  void _stopListening() {
    if (_isListening) {
      _speech.stop();
      setState(() => _isListening = false);
    }
  }

  Future<void> _callEmergencyNumber([String number = '1669']) async {
    final launchUri = Uri(scheme: 'tel', path: number);
    if (await canLaunchUrl(launchUri)) {
      await launchUrl(launchUri);
      return;
    }
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('ไม่สามารถโทรออกไปยัง $number ได้')),
    );
  }

  Future<void> _fetchGuidance(String sentence) async {
    if (sentence.trim().isEmpty ||
        sentence == 'กำลังฟัง...' ||
        sentence == 'กดปุ่มไมโครโฟนค้างไว้ เพื่อพูด') {
      setState(() {
        _voiceInputText = 'กดปุ่มไมโครโฟนค้างไว้ เพื่อพูด';
        _status = 'กรุณาพูดหรือพิมพ์รายละเอียดของเหตุการณ์';
      });
      return;
    }

    setState(() {
      _isLoading = true;
      _status = 'กำลังประมวลผลคำแนะนำ...';
    });
    FocusScope.of(context).unfocus();

    try {
      final userId = FirebaseAuth.instance.currentUser?.uid;
      double? latitude;
      double? longitude;
      try {
        LocationPermission permission = await Geolocator.checkPermission();
        if (permission == LocationPermission.denied) {
          permission = await Geolocator.requestPermission();
        }
        if (permission != LocationPermission.denied &&
            permission != LocationPermission.deniedForever) {
          final position = await Geolocator.getCurrentPosition(
            desiredAccuracy: LocationAccuracy.high,
            timeLimit: const Duration(seconds: 8),
          );
          latitude = position.latitude;
          longitude = position.longitude;
        }
      } catch (_) {
        // Location is optional for workflow; continue without it.
      }

      final workflowResponse = await _apiService.runAgentWorkflow(
        scenario: sentence,
        userId: userId,
        latitude: latitude,
        longitude: longitude,
      );
      if (mounted) {
        if (!workflowResponse.isEmergency ||
            workflowResponse.route == 'general_info') {
          Navigator.push(
            context,
            MaterialPageRoute(
              builder: (context) => GeneralInfoScreen(
                scenario: sentence,
                infoText: workflowResponse.generalInfo,
                triageReason: workflowResponse.triageReason,
              ),
            ),
          ).then((_) {
            setState(() {
              _voiceInputText = 'กดปุ่มไมโครโฟนค้างไว้ เพื่อพูด';
              _textEditingController.clear();
              _status = '';
              _isLoading = false;
            });
          });
          return;
        }

        Navigator.push(
          context,
          MaterialPageRoute(
            builder: (context) => ComprehensiveGuidanceScreen(
              guidanceText: workflowResponse.guidance,
              originalQuery: sentence,
              severity: workflowResponse.severity == 'moderate'
                  ? 'mild'
                  : workflowResponse.severity,
              facilityType: workflowResponse.facilityType,
              facilities: workflowResponse.facilities,
              callScript: workflowResponse.callScript,
            ),
          ),
        ).then((_) {
          setState(() {
            _voiceInputText = 'กดปุ่มไมโครโฟนค้างไว้ เพื่อพูด';
            _textEditingController.clear();
            _status = '';
            _isLoading = false;
          });
        });
      }
    } catch (e) {
      if (mounted) {
        Navigator.push(
          context,
          MaterialPageRoute(
            builder: (context) => GeneralFirstAidScreen(initialQuery: sentence),
          ),
        );
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content:
                Text('เชื่อมต่อระบบหลักไม่ได้ จึงเปิดคู่มือปฐมพยาบาลออฟไลน์'),
          ),
        );
        setState(() {
          _status = 'กำลังใช้งานโหมดออฟไลน์';
          _isLoading = false;
        });
      }
    }
    // No finally block needed for isLoading if handled in .then and catch
  }

  @override
  Widget build(BuildContext context) {
    final TextTheme appTextTheme = Theme.of(context).textTheme;
    final ColorScheme appColorScheme = Theme.of(context).colorScheme;

    return Scaffold(
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: const Color(0xFFFDECEA),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: const Color(0xFFE35D5B)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(
                      children: [
                        const Icon(Icons.warning_amber_rounded,
                            color: Color(0xFFB42318)),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            'ถ้าผู้ป่วยหมดสติ ไม่หายใจ หรือเลือดออกมาก ให้โทร 1669 ทันที',
                            style: appTextTheme.titleSmall?.copyWith(
                              fontWeight: FontWeight.w700,
                              color: const Color(0xFF7A271A),
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    ElevatedButton.icon(
                      onPressed: () => _callEmergencyNumber('1669'),
                      icon: const Icon(Icons.call),
                      label: const Text('โทร 1669 ตอนนี้'),
                      style: ElevatedButton.styleFrom(
                        minimumSize: const Size(double.infinity, 52),
                        backgroundColor: const Color(0xFFB42318),
                        foregroundColor: Colors.white,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 14),
              Card(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'เล่าเหตุการณ์สั้นๆ แล้วกดส่ง',
                        style: appTextTheme.titleLarge?.copyWith(
                          fontWeight: FontWeight.w700,
                          color: appColorScheme.primary,
                        ),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        'ระบบจะสรุปขั้นตอนฉุกเฉินแบบทีละข้อเพื่อให้ทำตามได้ง่าย',
                        style: appTextTheme.bodyMedium?.copyWith(
                          color: appTextTheme.bodyMedium?.color
                              ?.withValues(alpha: 0.8),
                        ),
                      ),
                      const SizedBox(height: 14),
                      TextField(
                        controller: _textEditingController,
                        decoration: InputDecoration(
                          hintText: 'ตัวอย่าง: พ่อหมดสติ ไม่หายใจ อยู่หน้าบ้าน',
                          suffixIcon: _textEditingController.text.isNotEmpty
                              ? IconButton(
                                  icon: Icon(Icons.clear,
                                      color: appColorScheme.primary
                                          .withValues(alpha: 0.7)),
                                  onPressed: () {
                                    _textEditingController.clear();
                                    setState(() {
                                      _voiceInputText =
                                          'กดปุ่มไมโครโฟนค้างไว้ เพื่อพูด';
                                    });
                                  },
                                )
                              : null,
                        ),
                        style: appTextTheme.bodyLarge,
                        minLines: 2,
                        maxLines: 4,
                        textInputAction: TextInputAction.done,
                        onSubmitted: (value) {
                          if (value.trim().isNotEmpty) {
                            _fetchGuidance(value.trim());
                          }
                        },
                      ),
                      const SizedBox(height: 12),
                      ElevatedButton.icon(
                        icon: const Icon(Icons.send),
                        label: const Text('ส่งเพื่อขอขั้นตอนช่วยเหลือ'),
                        onPressed: _isLoading
                            ? null
                            : () {
                                if (_textEditingController.text
                                    .trim()
                                    .isNotEmpty) {
                                  _fetchGuidance(
                                      _textEditingController.text.trim());
                                } else {
                                  setState(() {
                                    _status =
                                        'กรุณาพิมพ์รายละเอียดของเหตุการณ์';
                                  });
                                }
                              },
                        style: ElevatedButton.styleFrom(
                          minimumSize: const Size(double.infinity, 52),
                        ),
                      ),
                      const SizedBox(height: 8),
                      OutlinedButton.icon(
                        icon: const Icon(Icons.menu_book_outlined),
                        label: const Text('เปิดคู่มือปฐมพยาบาลออฟไลน์'),
                        onPressed: () {
                          Navigator.push(
                            context,
                            MaterialPageRoute(
                              builder: (context) =>
                                  const GeneralFirstAidScreen(),
                            ),
                          );
                        },
                        style: OutlinedButton.styleFrom(
                          minimumSize: const Size(double.infinity, 48),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 14),
              Card(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
                  child: Column(
                    children: [
                      Text(
                        _voiceInputText,
                        style: appTextTheme.bodyLarge?.copyWith(
                          fontStyle: FontStyle.italic,
                          color: appTextTheme.bodyLarge?.color
                              ?.withValues(alpha: 0.85),
                        ),
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 14),
                      _isLoading && !_isListening
                          ? Center(
                              child: CircularProgressIndicator(
                                valueColor: AlwaysStoppedAnimation<Color>(
                                  appColorScheme.primary,
                                ),
                              ),
                            )
                          : GestureDetector(
                              onLongPress: _listen,
                              onLongPressUp: _stopListening,
                              child: Container(
                                padding: const EdgeInsets.all(16),
                                decoration: BoxDecoration(
                                  color: _isListening
                                      ? microphoneListeningColor
                                      : microphoneColor,
                                  shape: BoxShape.circle,
                                  boxShadow: [
                                    BoxShadow(
                                      color:
                                          Colors.black.withValues(alpha: 0.2),
                                      spreadRadius: 1,
                                      blurRadius: 5,
                                      offset: const Offset(0, 3),
                                    ),
                                  ],
                                ),
                                child: Icon(
                                  _isListening ? Icons.mic_off : Icons.mic,
                                  color: Colors.white,
                                  size: 52,
                                ),
                              ),
                            ),
                      const SizedBox(height: 12),
                      Text(
                        _isListening
                            ? 'กำลังฟัง...'
                            : (_isLoading ? _status : 'กดค้างเพื่อพูด'),
                        textAlign: TextAlign.center,
                        style: appTextTheme.bodyMedium?.copyWith(
                          color: appTextTheme.bodyMedium?.color
                              ?.withValues(alpha: 0.75),
                        ),
                      ),
                      if (_status.isNotEmpty && !_isLoading && !_isListening)
                        Padding(
                          padding: const EdgeInsets.only(top: 10),
                          child: Text(
                            _status,
                            style: appTextTheme.bodySmall
                                ?.copyWith(color: appColorScheme.error),
                            textAlign: TextAlign.center,
                          ),
                        ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 16),
            ],
          ),
        ),
      ),
    );
  }
}
