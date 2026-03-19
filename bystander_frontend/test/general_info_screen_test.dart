import 'package:bystander_frontend/screens/general_info_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('GeneralInfoScreen renders key panic-safe messages',
      (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: GeneralInfoScreen(
          scenario: 'ปวดหัวเล็กน้อย',
          infoText: 'ไม่ใช่เหตุฉุกเฉิน',
          triageReason: 'ไม่มีสัญญาณอันตราย',
        ),
      ),
    );

    expect(find.textContaining('ไม่ใช่เหตุฉุกเฉิน'), findsWidgets);
    expect(find.textContaining('ปวดหัวเล็กน้อย'), findsOneWidget);
    expect(find.textContaining('โทร 1669'), findsWidgets);
  });
}
