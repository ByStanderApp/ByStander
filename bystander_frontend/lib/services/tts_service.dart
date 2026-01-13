import 'package:flutter_tts/flutter_tts.dart';

class TtsService {
  FlutterTts flutterTts = FlutterTts();
  bool _isInitialized = false;
  bool _isSpeaking = false;

  Future<void> initialize() async {
    if (_isInitialized) return;

    try {
      // First, check available languages
      List<dynamic> languages = await flutterTts.getLanguages;
      print('Available TTS languages: $languages');
      
      // Try to set Thai language - check for various Thai language codes
      String? thaiLanguage;
      if (languages.contains('th-TH')) {
        thaiLanguage = 'th-TH';
      } else if (languages.contains('th')) {
        thaiLanguage = 'th';
      } else {
        // Look for any Thai variant
        for (var lang in languages) {
          if (lang.toString().toLowerCase().startsWith('th')) {
            thaiLanguage = lang.toString();
            break;
          }
        }
      }
      
      if (thaiLanguage != null) {
        await flutterTts.setLanguage(thaiLanguage);
        print('TTS language set to: $thaiLanguage');
      } else {
        print('Warning: Thai language not found. Available: $languages');
        // Try to set it anyway - some platforms might accept it
        try {
          await flutterTts.setLanguage("th-TH");
          print('Set language to th-TH (may not be supported)');
        } catch (e) {
          print('Could not set th-TH, using default language');
        }
      }
      
      // Set speech rate (0.0 to 1.0, 0.5 is normal speed)
      await flutterTts.setSpeechRate(0.5);
      
      // Set pitch (0.5 to 2.0, 1.0 is normal)
      await flutterTts.setPitch(1.0);
      
      // Set volume (0.0 to 1.0, 1.0 is full volume)
      await flutterTts.setVolume(1.0);

      // Set completion handler
      flutterTts.setCompletionHandler(() {
        _isSpeaking = false;
      });

      // Set start handler
      flutterTts.setStartHandler(() {
        _isSpeaking = true;
      });

      // Set error handler
      flutterTts.setErrorHandler((msg) {
        print('TTS Error: $msg');
        _isSpeaking = false;
      });

      _isInitialized = true;
    } catch (e) {
      print('Error initializing TTS: $e');
      _isInitialized = true; // Still mark as initialized to avoid retrying
    }
  }

  Future<void> speak(String text) async {
    if (text.trim().isEmpty) return;

    if (!_isInitialized) {
      await initialize();
    }

    try {
      // Always try to set language to Thai before speaking (in case it was reset)
      List<dynamic> languages = await flutterTts.getLanguages;
      print('Available languages: $languages');
      
      // Try to set Thai language
      bool thaiSet = false;
      if (languages.contains('th-TH')) {
        await flutterTts.setLanguage('th-TH');
        print('Set language to th-TH');
        thaiSet = true;
      } else if (languages.contains('th')) {
        await flutterTts.setLanguage('th');
        print('Set language to th');
        thaiSet = true;
      } else {
        // Look for any Thai variant
        for (var lang in languages) {
          String langStr = lang.toString();
          if (langStr.toLowerCase().startsWith('th')) {
            await flutterTts.setLanguage(langStr);
            print('Set language to: $langStr');
            thaiSet = true;
            break;
          }
        }
      }
      
      if (!thaiSet) {
        print('Warning: Thai language not available. Available languages: $languages');
      }
      
      _isSpeaking = true;
      await flutterTts.speak(text);
    } catch (e) {
      print('Error speaking: $e');
      _isSpeaking = false;
    }
  }

  Future<void> stop() async {
    try {
      await flutterTts.stop();
      _isSpeaking = false;
    } catch (e) {
      print('Error stopping TTS: $e');
    }
  }

  Future<void> pause() async {
    try {
      await flutterTts.pause();
    } catch (e) {
      print('Error pausing TTS: $e');
    }
  }

  bool get isSpeaking => _isSpeaking;

  Future<List<dynamic>> getAvailableLanguages() async {
    try {
      return await flutterTts.getLanguages;
    } catch (e) {
      print('Error getting languages: $e');
      return [];
    }
  }
}
