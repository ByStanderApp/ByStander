// main.dart
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:bystander_frontend/screens/main_screen_host.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:bystander_frontend/services/runtime_asset_mode.dart';
import 'package:bystander_frontend/services/web_asset_probe_stub.dart'
    if (dart.library.html) 'package:bystander_frontend/services/web_asset_probe_web.dart';

import 'firebase_options.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final availability = await detectOnlineAssetsAvailability();
  RuntimeAssetMode.useOnlineMaps = availability.maps;
  RuntimeAssetMode.useOnlineFonts = availability.fonts;
  await Firebase.initializeApp(options: DefaultFirebaseOptions.currentPlatform);

  // One-time test write so you can see the app is connected to your Firestore:
  // Open Firebase Console → Firestore Database → Data → look for collection "connection_test"
  FirebaseFirestore.instance
      .collection('connection_test')
      .doc('app_start')
      .set({
    'message': 'ByStander connected',
    'at': FieldValue.serverTimestamp(),
  }).catchError((e) => null); // ignore errors (e.g. rules) so app still starts

  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    // Define custom colors based on user request
    const Color primaryColor =
        Color(0xFF36536B); // Darker blue for buttons, navbar, appbar
    const Color backgroundColor = Color(0xFF809FB4); // Main background color
    const Color cardBackgroundColor = Colors.white; // White cards for contrast
    final bool useOnlineFonts = RuntimeAssetMode.useOnlineFonts;
    final TextTheme themedText = useOnlineFonts
        ? GoogleFonts.sarabunTextTheme(Theme.of(context).textTheme)
        : Theme.of(context).textTheme;

    return MaterialApp(
      title: 'ByStander',
      theme: ThemeData(
        primaryColor: primaryColor,
        scaffoldBackgroundColor: backgroundColor,
        colorScheme: ColorScheme.fromSeed(
          seedColor: primaryColor,
          primary: primaryColor,
          secondary:
              primaryColor, // Using primary as secondary for now, can be adjusted
          surface:
              cardBackgroundColor, // This will be the default for Cards, Dialogs etc.
          onPrimary: Colors.white, // Text/icon color on primary color
          onSecondary: Colors.white, // Text/icon color on secondary color
          onSurface: Colors.black87, // Text/icon color on card/surface color
          error: Colors.redAccent, // Default error color
        ),
        textTheme: themedText.apply(
          bodyColor: const Color(
              0xFF102A43), // Darker text for better readability on light blue bg
          displayColor: const Color(0xFF102A43),
        ),
        appBarTheme: AppBarTheme(
          backgroundColor: primaryColor,
          foregroundColor: Colors.white, // Text and icons on AppBar
          titleTextStyle: useOnlineFonts
              ? GoogleFonts.prompt(
                  fontSize: 20,
                  fontWeight: FontWeight.bold,
                  color: Colors.white,
                )
              : const TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.bold,
                  color: Colors.white,
                ),
        ),
        elevatedButtonTheme: ElevatedButtonThemeData(
          style: ElevatedButton.styleFrom(
            backgroundColor: primaryColor,
            foregroundColor: Colors.white,
            padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(10),
            ),
            textStyle: useOnlineFonts
                ? GoogleFonts.sarabun(
                    fontSize: 16,
                    fontWeight: FontWeight.w600,
                  )
                : const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w600,
                  ),
          ),
        ),
        textButtonTheme: TextButtonThemeData(
          style: TextButton.styleFrom(
            foregroundColor: primaryColor,
            textStyle: useOnlineFonts
                ? GoogleFonts.sarabun(fontWeight: FontWeight.w600)
                : const TextStyle(fontWeight: FontWeight.w600),
          ),
        ),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: Colors.white.withValues(
              alpha: 0.7), // Slightly transparent white for text fields
          hintStyle: TextStyle(color: Colors.grey[600]),
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(10),
            borderSide: BorderSide.none, // No border by default, rely on fill
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(10),
            borderSide: const BorderSide(color: primaryColor, width: 2),
          ),
        ),
        cardTheme: CardThemeData(
          elevation: 3,
          color: cardBackgroundColor, // Explicitly set card color
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12.0),
          ),
          margin: const EdgeInsets.symmetric(vertical: 6, horizontal: 4),
        ),
        dividerTheme: DividerThemeData(
          color: primaryColor.withValues(alpha: 0.3),
          thickness: 1,
        ),
        bottomNavigationBarTheme: BottomNavigationBarThemeData(
          backgroundColor: primaryColor, // Navbar background
          selectedItemColor: Colors.white, // Selected icon and label
          unselectedItemColor:
              Colors.white.withValues(alpha: 0.6), // Unselected icon and label
          selectedLabelStyle: useOnlineFonts
              ? GoogleFonts.prompt(fontWeight: FontWeight.w600)
              : const TextStyle(fontWeight: FontWeight.w600),
          unselectedLabelStyle:
              useOnlineFonts ? GoogleFonts.prompt() : const TextStyle(),
        ),
        useMaterial3: true,
      ),
      builder: (context, child) {
        return MobileWebFrame(
          child: child ?? const SizedBox.shrink(),
        );
      },
      home: const MainScreenHost(),
      debugShowCheckedModeBanner: false,
    );
  }
}

class MobileWebFrame extends StatelessWidget {
  const MobileWebFrame({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    if (!kIsWeb) {
      return child;
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        if (constraints.maxWidth <= 600) {
          return child;
        }

        const frameWidth = 390.0;
        const frameHeight = 844.0;
        const borderRadius = BorderRadius.all(Radius.circular(36));

        return Container(
          decoration: const BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [Color(0xFFEAF3FA), Color(0xFFD4E4F0)],
            ),
          ),
          child: Center(
            child: Container(
              width: frameWidth,
              height: frameHeight,
              decoration: BoxDecoration(
                color: Colors.black,
                borderRadius: borderRadius,
                boxShadow: const [
                  BoxShadow(
                    color: Color(0x40000000),
                    blurRadius: 30,
                    offset: Offset(0, 18),
                  ),
                ],
              ),
              padding: const EdgeInsets.all(10),
              child: ClipRRect(
                borderRadius: const BorderRadius.all(Radius.circular(26)),
                child: MediaQuery(
                  data: MediaQuery.of(context).copyWith(
                    size: const Size(frameWidth, frameHeight),
                  ),
                  child: child,
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}
