import 'package:flutter/material.dart';

class PersonalInfoScreen extends StatelessWidget {
  const PersonalInfoScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final TextTheme appTextTheme = Theme.of(context).textTheme;
    final ColorScheme appColorScheme = Theme.of(context).colorScheme;
    const Color lightBlueBackground = Color(0xFFA9C3D6);

    return Scaffold(
      backgroundColor: lightBlueBackground,
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
                return const Icon(Icons.emergency_share_outlined, color: Colors.white);
              },
            ),
          ],
        ),
        centerTitle: true,
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          children: [
            // Title bar
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Text(
                'ข้อมูลส่วนตัวของผู้ใช้งาน',
                textAlign: TextAlign.center,
                style: appTextTheme.titleLarge?.copyWith(
                  fontWeight: FontWeight.bold,
                  color: Colors.black,
                ),
              ),
            ),
            const SizedBox(height: 20),

            // Profile picture placeholder
            CircleAvatar(
              radius: 50,
              backgroundColor: Colors.black,
              child: Icon(Icons.person, size: 60, color: Colors.white),
            ),
            const SizedBox(height: 30),

            // Name field
            _buildInfoField(
              label: 'ชื่อ นามสกุล',
              value: 'สมชาย รักดี',
              context: context,
            ),
            const SizedBox(height: 16),

            // Gender and Blood Type (side by side)
            Row(
              children: [
                Expanded(
                  child: _buildInfoField(
                    label: 'เพศ',
                    value: 'ชาย',
                    context: context,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: _buildInfoField(
                    label: 'หมู่เลือด',
                    value: 'O',
                    context: context,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),

            // Date of Birth
            _buildInfoField(
              label: 'วันเกิด',
              value: '12 ธันวาคม 1981',
              context: context,
            ),
            const SizedBox(height: 16),

            // Age
            _buildInfoField(
              label: 'อายุ',
              value: '45',
              context: context,
            ),
            const SizedBox(height: 16),

            // Phone Number
            _buildInfoField(
              label: 'เบอร์โทร',
              value: '099-999-9999',
              context: context,
            ),
            const SizedBox(height: 16),

            // Emergency Phone Number
            _buildInfoField(
              label: 'เบอร์โทรฉุกเฉิน',
              value: '1. ภรรยา: 088-888-8888\n2. ลูกสาว: 077-777-7777',
              context: context,
              isMultiLine: true,
            ),
            const SizedBox(height: 16),

            // Underlying Diseases
            _buildInfoField(
              label: 'โรคประจำตัว',
              value: '1. โรคหลอดเลือดหัวใจตีบ\n2. โรคเบาหวาน',
              context: context,
              isMultiLine: true,
            ),
            const SizedBox(height: 16),

            // Drug Allergies
            _buildInfoField(
              label: 'ยาที่แพ้',
              value: '1. tylenol',
              context: context,
            ),
            const SizedBox(height: 30),
          ],
        ),
      ),
    );
  }

  Widget _buildInfoField({
    required String label,
    required String value,
    required BuildContext context,
    bool isMultiLine = false,
  }) {
    final TextTheme appTextTheme = Theme.of(context).textTheme;
    
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(left: 4, bottom: 6),
          child: Text(
            label,
            style: appTextTheme.bodyMedium?.copyWith(
              fontWeight: FontWeight.w500,
              color: Colors.black87,
            ),
          ),
        ),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(10),
          ),
          child: Text(
            value,
            style: appTextTheme.bodyLarge?.copyWith(
              color: Colors.black,
            ),
          ),
        ),
      ],
    );
  }
}
