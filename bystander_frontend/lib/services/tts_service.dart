import 'dart:convert';
import 'dart:typed_data';

import 'package:audioplayers/audioplayers.dart';
import 'package:http/http.dart' as http;

class TtsService {
  static const String _googleTtsApiKey = String.fromEnvironment(
    'GOOGLE_TTS_API_KEY',
    defaultValue: '',
  );

  final AudioPlayer _audioPlayer = AudioPlayer();

  bool _isInitialized = false;
  bool _isSpeaking = false;

  Future<void> initialize() async {
    if (_isInitialized) return;

    try {
      _audioPlayer.onPlayerStateChanged.listen((PlayerState state) {
        _isSpeaking = state == PlayerState.playing;
      });

      _isInitialized = true;
    } catch (e) {
      print('Error initializing TTS: $e');
      _isInitialized = true;
    }
  }

  Future<void> speak(String text) async {
    if (text.trim().isEmpty) return;

    if (!_isInitialized) {
      await initialize();
    }

    try {
      if (_googleTtsApiKey.isEmpty) {
        print('Google TTS API key is missing. Pass GOOGLE_TTS_API_KEY via --dart-define.');
        _isSpeaking = false;
        return;
      }

      final Uri uri = Uri.parse(
        'https://texttospeech.googleapis.com/v1/text:synthesize?key=$_googleTtsApiKey',
      );

      final response = await http.post(
        uri,
        headers: {'Content-Type': 'application/json; charset=UTF-8'},
        body: jsonEncode({
          'input': {'text': text},
          'voice': {
            'languageCode': 'th-TH',
            'name': 'th-TH-Standard-A',
            'ssmlGender': 'FEMALE',
          },
          'audioConfig': {
            'audioEncoding': 'MP3',
            'speakingRate': 1.0,
            'pitch': 0.0,
          },
        }),
      );

      if (response.statusCode != 200) {
        print('Google TTS request failed: ${response.statusCode} ${response.body}');
        _isSpeaking = false;
        return;
      }

      final Map<String, dynamic> data = jsonDecode(response.body);
      final String? audioContent = data['audioContent'] as String?;

      if (audioContent == null || audioContent.isEmpty) {
        print('Google TTS returned empty audioContent.');
        _isSpeaking = false;
        return;
      }

      final Uint8List audioBytes = base64Decode(audioContent);
      _isSpeaking = true;
      await _audioPlayer.stop();
      await _audioPlayer.play(BytesSource(audioBytes));
    } catch (e) {
      print('Error speaking: $e');
      _isSpeaking = false;
    }
  }

  Future<void> stop() async {
    try {
      await _audioPlayer.stop();
      _isSpeaking = false;
    } catch (e) {
      print('Error stopping TTS: $e');
    }
  }

  Future<void> pause() async {
    try {
      await _audioPlayer.pause();
    } catch (e) {
      print('Error pausing TTS: $e');
    }
  }

  bool get isSpeaking => _isSpeaking;
}
