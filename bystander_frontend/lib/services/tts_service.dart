import 'dart:convert';
import 'dart:typed_data';

import 'package:audioplayers/audioplayers.dart';
import 'package:http/http.dart' as http;

class TtsService {
  static const String _ttsEndpoint =
      'https://bystander-7197.onrender.com/synthesize_speech';

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
      final Uri uri = Uri.parse(_ttsEndpoint);

      final response = await http.post(
        uri,
        headers: {'Content-Type': 'application/json; charset=UTF-8'},
        body: jsonEncode({
          'text': text,
        }),
      ).timeout(const Duration(seconds: 30));

      if (response.statusCode != 200) {
        String errorMessage = response.body;
        try {
          final parsed = jsonDecode(response.body) as Map<String, dynamic>;
          errorMessage = parsed['error']?.toString() ?? errorMessage;
        } catch (_) {}
        _isSpeaking = false;
        throw Exception('TTS request failed: $errorMessage');
      }

      final Map<String, dynamic> data = jsonDecode(response.body);
      final String? audioContent = data['audioContent'] as String?;

      if (audioContent == null || audioContent.isEmpty) {
        _isSpeaking = false;
        throw Exception('TTS returned empty audio');
      }

      final Uint8List audioBytes = base64Decode(audioContent);
      _isSpeaking = true;
      await _audioPlayer.stop();
      await _audioPlayer.play(BytesSource(audioBytes));
    } catch (e) {
      print('Error speaking: $e');
      _isSpeaking = false;
      rethrow;
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
