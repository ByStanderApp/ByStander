import 'dart:async';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';
import 'package:bystander_frontend/screens/home_screen.dart';
import 'package:bystander_frontend/screens/about_screen.dart';
import 'package:bystander_frontend/screens/personal_info_screen.dart';
import 'package:bystander_frontend/services/medical_context_cache_service.dart';

class MainScreenHost extends StatefulWidget {
  const MainScreenHost({super.key});

  @override
  State<MainScreenHost> createState() => _MainScreenHostState();
}

class _MainScreenHostState extends State<MainScreenHost>
    with WidgetsBindingObserver {
  StreamSubscription<User?>? _authSubscription;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    unawaited(MedicalContextCacheService.instance.refresh());
    _authSubscription = FirebaseAuth.instance.authStateChanges().listen((_) {
      unawaited(MedicalContextCacheService.instance.refresh());
    });
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      unawaited(MedicalContextCacheService.instance.refresh());
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _authSubscription?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          mainAxisSize: MainAxisSize.min,
          children: [
            Image.asset(
              'images/bystander_logo.png', // Corrected path as per user's pubspec
              height: 200,
              errorBuilder: (context, error, stackTrace) {
                print("Error loading logo: $error"); // Log error for debugging
                return const Icon(Icons.emergency_share_outlined,
                    color: Colors.white);
              },
            ),
            const SizedBox(width: 8),
          ],
        ),
        centerTitle: true,
        actions: [
          IconButton(
            icon: const Icon(Icons.person_outline, color: Colors.white),
            tooltip: 'ข้อมูลส่วนตัว',
            onPressed: () {
              Navigator.push(
                context,
                MaterialPageRoute(
                    builder: (context) => const PersonalInfoScreen()),
              );
            },
          ),
          IconButton(
            icon: const Icon(Icons.info_outline, color: Colors.white),
            tooltip: 'เกี่ยวกับแอปพลิเคชัน',
            onPressed: () {
              Navigator.push(
                context,
                MaterialPageRoute(builder: (context) => const AboutScreen()),
              );
            },
          ),
        ],
      ),
      body: const HomeScreen(),
    );
  }
}
