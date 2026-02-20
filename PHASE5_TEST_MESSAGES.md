# Phase 5 Test Messages - Quick Reference

Copy and paste these messages into your chat session to test preference extraction.

## Quick Test Sequence (Copy-Paste Ready)

```
I need a ride from Gaddafi Stadium to Johar Town

Book me a LUMI_GO ride from Model Town to F-6 Markaz

I'll pay with wallet this time

Take me to Johar Town again, use LUMI_PLUS

I need a ride tomorrow morning to Airport

Book Courier service from DHA to Gulberg

I usually go to Liberty Market in the evening, prefer LUMI_XL rides

I need to go from DHA Phase 5 to Airport, with a stop at Mall Road
```

## Individual Test Messages

### Test Pickup & Dropoff Extraction
```
I need a ride from Gaddafi Stadium to Johar Town
```

### Test Ride Type Extraction
```
Book me a LUMI_GO ride
```

### Test Complete Booking (Structured Data)
```
Book a ride from Model Town to F-6 Markaz using LUMI_PLUS, pay with wallet
```

### Test Payment Method
```
I'll pay with cash
```

### Test Time Preference
```
I need a ride tomorrow morning
```

### Test Frequency Tracking (Repeat Location)
```
Take me to Johar Town again
```

### Test Stops Extraction
```
I need to go from DHA Phase 5 to Airport, with a stop at Mall Road
```

### Test Natural Language (LLM Extraction)
```
I usually go to Liberty Market in the evening, prefer LUMI_XL rides
```

### Test Courier Service
```
Book a Courier service from my location to Gulberg
```

### Test Multiple Preferences in One Message
```
Book me a LUMI_PLUS ride from Model Town to F-6 Markaz, I'll pay with wallet, need it tomorrow morning
```

## Verification Commands

### Check preferences for a user:
```bash
python verify_preferences.py --user-id YOUR_USER_ID
```

### List all users with preferences:
```bash
python verify_preferences.py --all-users
```

### Check specific preference type:
```bash
python verify_preferences.py --user-id YOUR_USER_ID --type most_visited_place
```

## Expected Results

After running the test sequence, you should see preferences like:

- **Most Visited Places**: Johar Town (2x), F-6 Markaz, Airport, Gulberg, Liberty Market
- **Preferred Ride Types**: LUMI_GO, LUMI_PLUS, LUMI_XL, Courier
- **Common Pickup**: Gaddafi Stadium, Model Town, DHA Phase 5, DHA
- **Common Dropoff**: Johar Town (2x), F-6 Markaz, Airport, Gulberg, Liberty Market
- **Payment Methods**: WALLET, CASH
- **Time Preferences**: morning, evening
- **Stops**: Mall Road
