import 'package:flutter/material.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;
import 'package:permission_handler/permission_handler.dart';
import 'package:bystander_frontend/services/api_service.dart';
import 'package:bystander_frontend/screens/comprehensive_guidance_screen.dart';

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
  final Color microphoneColor = Colors.redAccent; // User specified color for mic button
  final Color microphoneListeningColor = const Color(0xFF36536B); // User specified this for listening state

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
        bool available = await _speech.initialize(
          onStatus: (val) {
            print('onStatus: $val');
            if (val == 'notListening' || val == 'done') {
              setState(() => _isListening = false);
              if (_voiceInputText.isNotEmpty &&
                  _voiceInputText != 'กำลังฟัง...' &&
                  _voiceInputText != 'กดปุ่มไมโครโฟนค้างไว้ เพื่อพูด') {
                _fetchGuidance(_voiceInputText);
              }
            }
          },
          onError: (val) {
            print('onError: $val');
            setState(() {
              _isListening = false;
              _status = 'เกิดข้อผิดพลาดในการฟัง: ${val.errorMsg}';
            });
          }
        );
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

  Future<void> _fetchGuidance(String sentence) async {
    if (sentence.trim().isEmpty || sentence == 'กำลังฟัง...' || sentence == 'กดปุ่มไมโครโฟนค้างไว้ เพื่อพูด') {
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
      final guidance = await _apiService.getGuidanceFromSentence(sentence);
      if (mounted) {
        Navigator.push(
          context,
          MaterialPageRoute(
            builder: (context) => ComprehensiveGuidanceScreen(
              guidanceText: guidance,
              originalQuery: sentence,
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
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('เกิดข้อผิดพลาด: ${e.toString()}')),
        );
         setState(() {
          _status = 'ข้อผิดพลาด: ${e.toString()}';
          _isLoading = false; // Ensure loading is reset on error too
        });
      }
    }
    // No finally block needed for isLoading if handled in .then and catch
  }

  @override
  Widget build(BuildContext context) {
    final TextTheme appTextTheme = Theme.of(context).textTheme;
    final ColorScheme appColorScheme = Theme.of(context).colorScheme;

    return Scaffold( // Scaffold already has background color from theme
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20.0),
        child: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              SizedBox(height: MediaQuery.of(context).size.height * 0.05),
              Text(
                'เหตุการณ์ฉุกเฉินที่เกิดขึ้น',
                style: appTextTheme.headlineSmall?.copyWith(
                    fontWeight: FontWeight.bold,
                    color: appColorScheme.primary), // Use primary color for title
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 25),
              TextField(
                controller: _textEditingController,
                decoration: InputDecoration(
                  hintText: 'หรือพิมพ์เหตุการณ์ที่นี่...',
                  // fillColor is handled by theme's inputDecorationTheme
                  suffixIcon: _textEditingController.text.isNotEmpty
                    ? IconButton(
                        icon: Icon(Icons.clear, color: appColorScheme.primary.withOpacity(0.7)),
                        onPressed: () {
                          _textEditingController.clear();
                          setState(() {
                            _voiceInputText = 'กดปุ่มไมโครโฟนค้างไว้ เพื่อพูด';
                          });
                        },
                      )
                    : null,
                ),
                style: appTextTheme.bodyLarge,
                minLines: 1,
                maxLines: 3,
                textInputAction: TextInputAction.done,
                onSubmitted: (value) {
                   if (value.trim().isNotEmpty) {
                    _fetchGuidance(value.trim());
                  }
                },
              ),
              const SizedBox(height: 15),
              ElevatedButton.icon(
                icon: const Icon(Icons.send), // color is handled by theme
                label: const Text('ส่งข้อมูล'), // style is handled by theme
                // style is handled by theme
                onPressed: _isLoading ? null : () {
                  if (_textEditingController.text.trim().isNotEmpty) {
                    _fetchGuidance(_textEditingController.text.trim());
                  } else {
                     setState(() {
                       _status = 'กรุณาพิมพ์รายละเอียดของเหตุการณ์';
                     });
                  }
                },
              ),
              const SizedBox(height: 25),
              Row(
                children: <Widget>[
                  const Expanded(child: Divider()), // color from theme
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 8.0),
                    child: Text("หรือ", style: appTextTheme.bodyMedium?.copyWith(color: appTextTheme.bodyMedium?.color?.withOpacity(0.7))),
                  ),
                  const Expanded(child: Divider()), // color from theme
                ],
              ),
              const SizedBox(height: 25),
              Text(
                _voiceInputText,
                style: appTextTheme.bodyLarge?.copyWith(fontStyle: FontStyle.italic, color: appTextTheme.bodyLarge?.color?.withOpacity(0.8)),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 20),
              _isLoading && !_isListening
                  ? Center(
                      child: CircularProgressIndicator(
                        valueColor: AlwaysStoppedAnimation<Color>(appColorScheme.primary),
                      ),
                    )
                  : GestureDetector(
                      onLongPress: _listen,
                      onLongPressUp: _stopListening,
                      child: Container(
                        padding: const EdgeInsets.all(15),
                        decoration: BoxDecoration(
                          color: _isListening ? microphoneListeningColor : microphoneColor,
                          shape: BoxShape.circle,
                          boxShadow: [
                            BoxShadow(
                              color: Colors.black.withOpacity(0.2),
                              spreadRadius: 1,
                              blurRadius: 5,
                              offset: const Offset(0, 3),
                            ),
                          ],
                        ),
                        child: Icon(
                          _isListening ? Icons.mic_off : Icons.mic,
                          color: Colors.white, // Icon color on mic button
                          size: 50,
                        ),
                      ),
                    ),
              const SizedBox(height: 15),
              Text(
                _isListening ? 'กำลังฟัง...' : (_isLoading ? _status : 'กดค้างเพื่อพูด'),
                textAlign: TextAlign.center,
                style: appTextTheme.bodyMedium?.copyWith(color: appTextTheme.bodyMedium?.color?.withOpacity(0.7)),
              ),
               if (_status.isNotEmpty && !_isLoading && !_isListening)
                Padding(
                  padding: const EdgeInsets.only(top: 10.0),
                  child: Text(
                    _status,
                    style: appTextTheme.bodySmall?.copyWith(color: appColorScheme.error),
                    textAlign: TextAlign.center,
                  ),
                ),
              SizedBox(height: MediaQuery.of(context).size.height * 0.05),
            ],
          ),
        ),
      ),
    );
  }
}