import 'dart:convert';
import 'package:http/http.dart' as http;

class ApiService {
  // !!! IMPORTANT: Replace with your Flask API's actual IP address and port !!!
  // If running Flask locally and testing on an emulator:
  // - Android Emulator: usually 'http://10.0.2.2:5000'
  // - iOS Simulator: usually 'http://localhost:5000' or 'http://127.0.0.1:5000'
  // If testing on a physical device, use your computer's network IP address:
  // e.g., 'http://192.168.1.100:5000'
  static const String _baseUrl = 'http://localhost:5001'; 

  Future<String> getGuidanceFromSentence(String sentence) async {
    final Uri url = Uri.parse('$_baseUrl/generate_guidance_sentence_only');
    try {
      final response = await http.post(
        url,
        headers: {'Content-Type': 'application/json; charset=UTF-8'},
        body: jsonEncode({'sentence': sentence}),
      ).timeout(const Duration(seconds: 30)); 

      if (response.statusCode == 200) {
        final responseBody = utf8.decode(response.bodyBytes); 
        final data = jsonDecode(responseBody);
        if (data.containsKey('guidance')) {
          return data['guidance'];
        } else if (data.containsKey('error')) {
          throw Exception('API Error: ${data['error']}');
        } else {
          throw Exception('Invalid response format from API');
        }
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
        throw Exception('Failed to get guidance from API. Status: ${response.statusCode}, Message: $errorMessage');
      }
    } catch (e) {
      print('ApiService Error: $e');
      throw Exception('ไม่สามารถเชื่อมต่อกับเซิร์ฟเวอร์ได้: ${e.toString()}');
    }
  }
}