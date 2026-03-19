import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

class GeneralInfoScreen extends StatelessWidget {
  final String scenario;
  final String infoText;
  final String triageReason;

  const GeneralInfoScreen({
    super.key,
    required this.scenario,
    required this.infoText,
    this.triageReason = '',
  });

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final colorScheme = Theme.of(context).colorScheme;

    Future<void> call1669() async {
      final uri = Uri(scheme: 'tel', path: '1669');
      if (await canLaunchUrl(uri)) {
        await launchUrl(uri);
        return;
      }
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('ไม่สามารถโทรออก 1669 ได้')),
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('ข้อมูลทั่วไป'),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: const Color(0xFFEAF7F1),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                    color: const Color(0xFF1E6A52).withValues(alpha: 0.4)),
              ),
              child: Text(
                'ผลการประเมินเบื้องต้น: ไม่ใช่เหตุฉุกเฉิน',
                style: textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.bold,
                  color: const Color(0xFF1E6A52),
                ),
              ),
            ),
            const SizedBox(height: 12),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Text(
                  'สถานการณ์ที่แจ้ง: $scenario',
                  style: textTheme.bodyLarge?.copyWith(height: 1.45),
                ),
              ),
            ),
            const SizedBox(height: 10),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Text(
                  infoText.isNotEmpty
                      ? infoText
                      : 'สถานการณ์นี้ยังไม่เข้าข่ายเหตุฉุกเฉินเร่งด่วน',
                  style: textTheme.bodyLarge?.copyWith(height: 1.45),
                ),
              ),
            ),
            if (triageReason.trim().isNotEmpty) ...[
              const SizedBox(height: 10),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Text(
                    'เหตุผลจากระบบ: $triageReason',
                    style: textTheme.bodyMedium?.copyWith(
                      color: colorScheme.primary.withValues(alpha: 0.92),
                    ),
                  ),
                ),
              ),
            ],
            const SizedBox(height: 14),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: const Color(0xFFFDECEA),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: const Color(0xFFE35D5B)),
              ),
              child: Text(
                'ถ้าอาการเปลี่ยนเป็นหมดสติ หายใจลำบาก เจ็บหน้าอกรุนแรง หรือมีเลือดออกมาก ให้โทร 1669 ทันที',
                style: textTheme.bodyMedium?.copyWith(
                  color: const Color(0xFF7A271A),
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                icon: const Icon(Icons.call),
                label: const Text('โทร 1669 ทันที หากอาการแย่ลง'),
                onPressed: call1669,
                style: ElevatedButton.styleFrom(
                  minimumSize: const Size(double.infinity, 50),
                  backgroundColor: const Color(0xFFB42318),
                  foregroundColor: Colors.white,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
