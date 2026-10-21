// SentryCare badge settings.
// Copy this file to "config.h" (same folder) and fill in your details.
// config.h is ignored by git, so your Wi-Fi password never gets pushed.

#pragma once

// Wi-Fi the badge joins. Must be 2.4 GHz: the badge cannot see 5 GHz networks.
// A phone hotspot works well at venues (set it to 2.4 GHz / "maximise compatibility").
#define WIFI_SSID      "your-wifi-name"
#define WIFI_PASSWORD  "your-wifi-password"

// The laptop running badge_server.py, on the SAME Wi-Fi.
// Find its address on Linux with:  hostname -I   (use the first number, e.g. 192.168.1.23)
#define SERVER_HOST    "192.168.1.23"
#define SERVER_PORT    8000

// Who wears this badge. Shows on the nurses' screen next to each action.
#define BADGE_NAME     "badge-1"

// Language the badge speaks back in: "te-IN" Telugu.
#define REPLY_LANGUAGE "te-IN"

// Voice: "ishita" (female) or "shubh" (male).
#define VOICE          "ishita"
