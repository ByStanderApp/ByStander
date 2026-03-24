class AppConfig {
  // Override at runtime:
  // flutter run --dart-define=BYSTANDER_API_BASE_URL=http://127.0.0.1:5003
  static const String _apiBaseUrlRaw = String.fromEnvironment(
    'BYSTANDER_API_BASE_URL',
    defaultValue: 'https://bystander-7197.onrender.com',
  );

  static String get apiBaseUrl =>
      _apiBaseUrlRaw.endsWith('/') && _apiBaseUrlRaw.length > 1
          ? _apiBaseUrlRaw.substring(0, _apiBaseUrlRaw.length - 1)
          : _apiBaseUrlRaw;
}

