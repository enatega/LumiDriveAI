# Enable Google Maps Time Zone API

The `REQUEST_DENIED` error means the Google Maps Time Zone API is not enabled in your Google Cloud project.

## Steps to Enable the API

1. **Go to Google Cloud Console**
   - Visit: https://console.cloud.google.com/

2. **Select Your Project**
   - Make sure you're working in the same project where your Google Maps API key is configured

3. **Navigate to APIs & Services > Library**
   - In the left sidebar, go to "APIs & Services" > "Library"
   - Or visit directly: https://console.cloud.google.com/apis/library

4. **Search for "Time Zone API"**
   - In the search bar, type: `Time Zone API`
   - Click on "Time Zone API" from the results

5. **Enable the API**
   - Click the "ENABLE" button

6. **Verify API Key Access**
   - Go to "APIs & Services" > "Credentials"
   - Click on your API key (the one you're using in GOOGLE_API_KEY)
   - Under "API restrictions":
     - Make sure "Time Zone API" is included in the allowed APIs list
     - Or set it to "Don't restrict key" (less secure but easier for development)

7. **Wait a Few Minutes**
   - API enablement can take 1-2 minutes to propagate
   - Try your request again after waiting

## Alternative: Enable via Command Line (if you have gcloud CLI)

```bash
gcloud services enable timezone-backend.googleapis.com --project=YOUR_PROJECT_ID
```

Replace `YOUR_PROJECT_ID` with your actual Google Cloud project ID.

## Verify It's Enabled

After enabling, you can verify by:
1. Going to "APIs & Services" > "Enabled APIs"
2. Searching for "Time Zone API"
3. It should appear in the list

## Important Notes

- **Billing**: Make sure billing is enabled for your Google Cloud project (Time Zone API requires billing)
- **Quotas**: Check your quotas to ensure you have available quota
- **API Key**: The same API key you use for other Google Maps APIs will work for Time Zone API

## Cost

The Time Zone API has a free tier:
- Free: $200 credit per month (covers most usage)
- Pricing: $5.00 per 1,000 requests after free tier

For most applications, you'll stay within the free tier.

