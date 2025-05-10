import 'package:flutter/material.dart';

class AboutScreen extends StatelessWidget {
  const AboutScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final TextTheme appTextTheme = Theme.of(context).textTheme;
    final ColorScheme appColorScheme = Theme.of(context).colorScheme;

    return Scaffold(
       appBar: AppBar(
        title: const Text('เกี่ยวกับแอปพลิเคชัน'),
        // Theme applied from main.dart
      ),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(16.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: <Widget>[
              Image.asset(
                'images/bystander_logo.png', // Corrected path
                 height: 80,
                 errorBuilder: (context, error, stackTrace) {
                    print("Error loading logo in AboutScreen: $error");
                    return Icon(Icons.support_agent, size: 80, color: appColorScheme.primary);
                 },
              ),
              const SizedBox(height: 20),
              Text(
                'ByStander Application',
                style: appTextTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold, color: appColorScheme.primary),
              ),
              const SizedBox(height: 10),
              Text(
                'แอปพลิเคชันแนะนำการปฐมพยาบาลเบื้องต้นในสถานการณ์ฉุกเฉิน',
                textAlign: TextAlign.center,
                style: appTextTheme.titleMedium?.copyWith(color: appTextTheme.titleMedium?.color?.withOpacity(0.8)),
              ),
              const SizedBox(height: 20),
              Text(
                'เวอร์ชัน 1.0.0',
                style: appTextTheme.bodySmall?.copyWith(color: appTextTheme.bodySmall?.color?.withOpacity(0.7)),
              ),
              const SizedBox(height: 30),
               Text(
                'พัฒนาโดย: Amy Worawalan', // Replace with your name
                style: appTextTheme.bodySmall?.copyWith(color: appTextTheme.bodySmall?.color?.withOpacity(0.7)),
              ),
            ],
          ),
        ),
      ),
    );
  }
}