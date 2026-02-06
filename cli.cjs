const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const readline = require('readline');
const mqtt = require('mqtt');

// Helper to de-obfuscate
const _mj = (arr) => arr.map(c => String.fromCharCode(c ^ 0x55)).join('');

// --- Configuration ---
const CONFIG = {
    clientId: _mj([120, 13, 38, 30, 98, 26, 99, 60, 16, 62, 25, 56, 57, 98, 98, 44, 17, 18, 17, 0, 60, 101, 62, 32]),
    clientSecret: _mj([3, 102, 97, 23, 57, 20, 61, 32, 60, 57, 28, 49, 26, 45, 101, 28, 56, 58, 100, 99, 39, 18, 4, 103]),
    redirectUri: 'com.philips.air://loginredirect',
    scope: 'openid email profile address DI.Account.read DI.AccountProfile.read DI.AccountProfile.write DI.AccountGeneralConsent.read DI.AccountGeneralConsent.write DI.GeneralConsent.read subscriptions profile_extended consents DI.AccountSubscription.read DI.AccountSubscription.write',
    authUrl: 'https://cdc.accounts.home.id/oidc/op/v1.0/4_JGZWlP8eQHpEqkvQElolbA/authorize',
    tokenUrl: 'https://cdc.accounts.home.id/oidc/op/v1.0/4_JGZWlP8eQHpEqkvQElolbA/oauth/token',
    apiBase: 'https://prod.eu-da.iot.versuni.com/api/da',
    userAgent: 'Air (com.philips.ph.homecare; build:3.16.1; locale:en_US; Android:12 Sdk:2.2.0) okhttp/4.12.0',
    tokenFile: path.join(__dirname, 'philips_tokens.json')
};

// --- Helpers ---
function base64URLEncode(str) {
    return str.toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

function generateVerifier() {
    return base64URLEncode(crypto.randomBytes(32));
}

function generateChallenge(verifier) {
    return base64URLEncode(crypto.createHash('sha256').update(verifier).digest());
}

function uuidv4() {
    return crypto.randomUUID();
}

// --- Token Management ---
function saveTokens(tokens) {
    tokens.expires_at = Date.now() + (tokens.expires_in * 1000);
    fs.writeFileSync(CONFIG.tokenFile, JSON.stringify(tokens, null, 2));
    console.log('✅ Tokens (Access + ID) saved to disk.');
}

function loadTokens() {
    if (fs.existsSync(CONFIG.tokenFile)) {
        return JSON.parse(fs.readFileSync(CONFIG.tokenFile));
    }
    return null;
}

// --- API Client ---
async function apiCall(endpoint, method = 'GET', token, body = null, useBearer = true) {
    const headers = {
        'User-Agent': CONFIG.userAgent,
        'Content-Type': 'application/json'
    };

    if (useBearer && token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const options = { method, headers };
    if (body) options.body = JSON.stringify(body);

    const response = await fetch(`${CONFIG.apiBase}${endpoint}`, options);
    if (!response.ok) {
        throw new Error(`API Error ${response.status} on ${endpoint}: ${await response.text()}`);
    }
    return await response.json();
}

// --- Auth Flow ---
async function login() {
    let tokens = loadTokens();

    if (tokens) {
        if (Date.now() < tokens.expires_at - 60000) {
            console.log('🔹 Using existing valid tokens.');
            return tokens; // Return full object (access_token + id_token)
        } else {
            console.log('🔸 Token expired. Refreshing...');
            try {
                return await refreshToken(tokens.refresh_token);
            } catch (e) {
                console.error('❌ Refresh failed. Restarting login flow.');
            }
        }
    }

    // Full PKCE Login
    const verifier = generateVerifier();
    const challenge = generateChallenge(verifier);
    const params = new URLSearchParams({
        client_id: CONFIG.clientId,
        code_challenge: challenge,
        code_challenge_method: 'S256',
        response_type: 'code',
        redirect_uri: CONFIG.redirectUri,
        ui_locales: 'en-US',
        scope: CONFIG.scope
    });

    console.log('\n👉 Open this URL to login:', `${CONFIG.authUrl}?${params.toString()}\n`);

    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });

    return new Promise((resolve) => {
        rl.question('Paste redirect URL: ', async (pastedUrl) => {
            rl.close();
            try {
                const cleanUrl = pastedUrl.trim().replace(/'/g, '').replace(/"/g, '');
                const parsedUrl = new URL(cleanUrl.replace('com.philips.air://', 'http://dummy/'));
                const code = parsedUrl.searchParams.get('code');
                if (!code) throw new Error('No code found');

                const response = await fetch(CONFIG.tokenUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: new URLSearchParams({
                        client_id: CONFIG.clientId,
                        code: code,
                        grant_type: 'authorization_code',
                        redirect_uri: CONFIG.redirectUri,
                        client_secret: CONFIG.clientSecret,
                        code_verifier: verifier
                    })
                });

                const data = await response.json();
                if (data.error) throw new Error(data.error);

                saveTokens(data);
                resolve(data);
            } catch (error) {
                console.error('❌ Login failed:', error.message);
                process.exit(1);
            }
        });
    });
}

async function refreshToken(refreshToken) {
    const response = await fetch(CONFIG.tokenUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({
            client_id: CONFIG.clientId,
            client_secret: CONFIG.clientSecret,
            grant_type: 'refresh_token',
            refresh_token: refreshToken
        })
    });
    const data = await response.json();
    if (data.error) throw new Error(data.error);
    saveTokens(data);
    return data;
}

// --- Main Logic ---
async function main() {
    try {
        // 1. Authenticate (Get both tokens)
        const tokens = await login();
        const accessToken = tokens.access_token;
        const idToken = tokens.id_token;

        if (!idToken) {
            throw new Error("❌ ID Token missing. Please delete philips_tokens.json and login again.");
        }

        // 2. Fetch User ID for ClientId construction
        // Request 240 in HAR: Uses idToken in body, NO Bearer header
        console.log('🔹 Fetching User ID...');
        const userRes = await apiCall('/user/self/get-id', 'POST', null, { idToken: idToken }, false);
        const userId = userRes.userId;
        console.log(`✅ User ID: ${userId}`);

        // 3. Get Device Info
        console.log('🔹 Fetching devices...');
        const devices = await apiCall('/user/self/device', 'GET', accessToken);
        const myDevice = devices[0];
        console.log(`✅ Found device: ${myDevice.friendlyName} (${myDevice.thingName})`);

        // 4. Get AWS Signature
        console.log('🔹 Getting AWS Signature...');
        const sigData = await apiCall('/user/self/signature', 'GET', accessToken);
        const signature = sigData.signature;
        console.log('✅ Signature obtained.');

        // 5. Connect to AWS IoT
        console.log('🔹 Connecting to AWS IoT...');

        // FIX: Construct the specific Client ID format: I<userId>_<randomUUID>
        const clientId = `${userId}_${uuidv4()}`;
        console.log(`🔹 Using Client ID: ${clientId}`);

        const client = mqtt.connect('wss://ats.prod.eu-da.iot.versuni.com/mqtt', {
            clientId: clientId,
            protocolId: 'MQTT',
            protocolVersion: 4,
            clean: true,
            keepalive: 30,
            reconnectPeriod: 5000,

            wsOptions: {
                headers: {
                    'token-header': `Bearer ${accessToken}`,
                    'x-amz-customauthorizer-signature': signature,
                    'x-amz-customauthorizer-name': 'CustomAuthorizer',
                    'tenant': 'da'
                },
                protocol: 'mqtt'
            }
        });

        client.on('connect', () => {
            console.log('🚀 MQTT Connected!');

            const shadowTopic = `$aws/things/${myDevice.thingName}/shadow/update`;
            const acceptedTopic = `${shadowTopic}/accepted`;

            client.subscribe([acceptedTopic], (err) => {
                if (!err) console.log(`📡 Subscribed to shadow updates`);
            });

            // Toggle logic
            setTimeout(() => {
                console.log('💡 Sending Power Command...');
                client.publish(shadowTopic, JSON.stringify({
                    state: { desired: { powerOn: false } }
                }));
            }, 2000);
        });

        client.on('message', (topic, message) => {
            console.log(`📩 [${topic}]: ${message.toString()}`);
        });

        client.on('error', (err) => console.error('❌ MQTT Error:', err.message));
        client.on('offline', () => console.log('🔸 MQTT Offline'));
        client.on('close', () => console.log('🔸 MQTT Connection Closed'));

    } catch (error) {
        console.error('❌ Application Error:', error);
    }
}

main();