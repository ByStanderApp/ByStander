import 'dart:async';
import 'dart:html' as html;
import 'package:bystander_frontend/services/runtime_asset_mode.dart';

bool _readBool(String key, {bool fallback = false}) {
  try {
    // `dart:js_util` isn't available in some Dart SDK builds, so access the
    // window global dynamically instead.
    final dynamic win = html.window;
    final value = win[key];
    if (value is bool) return value;
    return fallback;
  } catch (_) {
    return fallback;
  }
}

Future<OnlineAssetAvailability> detectOnlineAssetsAvailability({
  Duration timeout = const Duration(seconds: 4),
}) async {
  final readyNow = _readBool('__bystanderOnlineAssetsReady');
  if (readyNow) {
    return OnlineAssetAvailability(
      maps: _readBool('__bystanderOnlineMaps'),
      fonts: _readBool('__bystanderOnlineFonts'),
    );
  }

  final completer = Completer<OnlineAssetAvailability>();

  late html.EventListener listener;
  listener = (_) {
    if (!completer.isCompleted) {
      completer.complete(
        OnlineAssetAvailability(
          maps: _readBool('__bystanderOnlineMaps'),
          fonts: _readBool('__bystanderOnlineFonts'),
        ),
      );
    }
  };

  html.window.addEventListener('bystander-assets-ready', listener);

  try {
    return await completer.future.timeout(
      timeout,
      onTimeout: () => OnlineAssetAvailability(
        maps: _readBool('__bystanderOnlineMaps'),
        fonts: _readBool('__bystanderOnlineFonts'),
      ),
    );
  } finally {
    html.window.removeEventListener('bystander-assets-ready', listener);
  }
}
