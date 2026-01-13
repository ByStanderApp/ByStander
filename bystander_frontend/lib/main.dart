// main.dart
import 'package:flutter/material.dart';
import 'package:bystander_frontend/screens/main_screen_host.dart';
import 'package:google_fonts/google_fonts.dart';

void main() {
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    // Define custom colors based on user request
    const Color primaryColor = Color(0xFF36536B); // Darker blue for buttons, navbar, appbar
    const Color backgroundColor = Color(0xFF809FB4); // Main background color
    const Color microphoneListeningColor = Color(0xFF36536B); // User specified this color for listening state
    const Color cardBackgroundColor = Colors.white; // White cards for contrast

    return MaterialApp(
      title: 'ByStander',
      theme: ThemeData(
        primaryColor: primaryColor,
        scaffoldBackgroundColor: backgroundColor,
        colorScheme: ColorScheme.fromSeed(
          seedColor: primaryColor,
          primary: primaryColor,
          secondary: primaryColor, // Using primary as secondary for now, can be adjusted
          background: backgroundColor,
          surface: cardBackgroundColor, // This will be the default for Cards, Dialogs etc.
          onPrimary: Colors.white, // Text/icon color on primary color
          onSecondary: Colors.white, // Text/icon color on secondary color
          onBackground: Colors.black87, // Text/icon color on background color
          onSurface: Colors.black87, // Text/icon color on card/surface color
          error: Colors.redAccent, // Default error color
        ),
        textTheme: GoogleFonts.sarabunTextTheme(
          Theme.of(context).textTheme,
        ).apply(
          bodyColor: const Color(0xFF102A43), // Darker text for better readability on light blue bg
          displayColor: const Color(0xFF102A43),
        ),
        appBarTheme: AppBarTheme(
          backgroundColor: primaryColor,
          foregroundColor: Colors.white, // Text and icons on AppBar
          titleTextStyle: GoogleFonts.prompt(
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
            textStyle: GoogleFonts.sarabun(fontSize: 16, fontWeight: FontWeight.w600),
          ),
        ),
        textButtonTheme: TextButtonThemeData(
          style: TextButton.styleFrom(
            foregroundColor: primaryColor,
            textStyle: GoogleFonts.sarabun(fontWeight: FontWeight.w600),
          )
        ),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: Colors.white.withOpacity(0.7), // Slightly transparent white for text fields
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
          color: primaryColor.withOpacity(0.3),
          thickness: 1,
        ),
        bottomNavigationBarTheme: BottomNavigationBarThemeData(
          backgroundColor: primaryColor, // Navbar background
          selectedItemColor: Colors.white, // Selected icon and label
          unselectedItemColor: Colors.white.withOpacity(0.6), // Unselected icon and label
          selectedLabelStyle: GoogleFonts.prompt(fontWeight: FontWeight.w600),
          unselectedLabelStyle: GoogleFonts.prompt(),
        ),
        useMaterial3: true,
      ),
      home: const MainScreenHost(),
      debugShowCheckedModeBanner: false,
    );
  }
}