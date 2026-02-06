const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const readline = require('readline');
const mqtt = require('mqtt');
const http = require('http');

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
    tokenFile: path.join(__dirname, 'philips_tokens.json'),
    serverPort: 3000
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

function getTimestamp() {
    // Format: YYYY-MM-DDTHH:mm:ssZ (No milliseconds, based on HAR)
    return new Date().toISOString().split('.')[0] + 'Z';
}

// --- Token Management ---
function saveTokens(tokens) {
    tokens.expires_at = Date.now() + ((tokens.expires_in || 3600) * 1000);
    fs.writeFileSync(CONFIG.tokenFile, JSON.stringify(tokens, null, 2));
    console.log('✅ Tokens saved to disk.');
}

function loadTokens() {
    if (fs.existsSync(CONFIG.tokenFile)) {
        return JSON.parse(fs.readFileSync(CONFIG.tokenFile));
    }
    return null;
}

// --- API Client ---
async function apiCall(endpoint, method = 'GET', token, body = null, useBearer = true) {
    const headers = { 'User-Agent': CONFIG.userAgent, 'Content-Type': 'application/json' };
    if (useBearer && token) headers['Authorization'] = `Bearer ${token}`;

    const options = { method, headers };
    if (body) options.body = JSON.stringify(body);

    const response = await fetch(`${CONFIG.apiBase}${endpoint}`, options);
    if (!response.ok) throw new Error(`API Error ${response.status}: ${await response.text()}`);
    return await response.json();
}

// --- Auth Flow ---
async function login() {
    let tokens = loadTokens();
    if (tokens) {
        if (Date.now() < tokens.expires_at - 60000) {
            console.log('🔹 Using existing valid token.');
            return tokens;
        } else {
            console.log('🔸 Token expired. Refreshing...');
            try { return await refreshToken(tokens.refresh_token); }
            catch (e) { console.error('❌ Refresh failed. Restarting login flow.'); }
        }
    }

    const verifier = generateVerifier();
    const challenge = generateChallenge(verifier);
    const params = new URLSearchParams({
        client_id: CONFIG.clientId, code_challenge: challenge, code_challenge_method: 'S256',
        response_type: 'code', redirect_uri: CONFIG.redirectUri, ui_locales: 'en-US', scope: CONFIG.scope
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
                        client_id: CONFIG.clientId, code, grant_type: 'authorization_code',
                        redirect_uri: CONFIG.redirectUri, client_secret: CONFIG.clientSecret, code_verifier: verifier
                    })
                });
                const data = await response.json();
                if (data.error) throw new Error(data.error);
                saveTokens(data);
                resolve(data);
            } catch (error) { console.error('❌ Login failed:', error.message); process.exit(1); }
        });
    });
}

async function refreshToken(refreshToken) {
    const response = await fetch(CONFIG.tokenUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({
            client_id: CONFIG.clientId, client_secret: CONFIG.clientSecret,
            grant_type: 'refresh_token', refresh_token: refreshToken
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
        const tokens = await login();
        const accessToken = tokens.access_token;
        const idToken = tokens.id_token;
        if (!idToken) throw new Error("❌ ID Token missing. Delete philips_tokens.json and login again.");

        console.log('🔹 Fetching User ID...');
        const userRes = await apiCall('/user/self/get-id', 'POST', null, { idToken: idToken }, false);
        const userId = userRes.userId;

        console.log('🔹 Fetching devices...');
        const devices = await apiCall('/user/self/device', 'GET', accessToken);
        const myDevice = devices[0];
        if (!myDevice) { console.error('❌ No devices found.'); return; }
        console.log(`✅ Found: ${myDevice.friendlyName} (${myDevice.thingName})`);

        console.log('🔹 Getting AWS Signature...');
        const sigData = await apiCall('/user/self/signature', 'GET', accessToken);
        const signature = sigData.signature;
        console.log('✅ Signature obtained.');

        console.log('🔹 Connecting to AWS IoT...');
        const clientId = `${userId}_${uuidv4()}`;
        const wsUrl = 'wss://ats.prod.eu-da.iot.versuni.com/mqtt';

        const client = mqtt.connect(wsUrl, {
            clientId: clientId, protocolId: 'MQTT', protocolVersion: 4, clean: true, keepalive: 30, reconnectPeriod: 5000,
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

            // Topics
            const shadowTopic = `$aws/things/${myDevice.thingName}/shadow/update`;
            const acceptedTopic = `${shadowTopic}/accepted`;

            // This is the NEW topic we discovered for mode control [Source: ws-indepth.har]
            const ncpTopic = `da_ctrl/${myDevice.thingName}/to_ncp`;

            client.subscribe([acceptedTopic], (err) => {
                if (!err) console.log(`📡 Listening for state updates...`);
            });

            // Helper to send "Mode" commands
            const setMode = (value) => {
                // Command structure reversed from HAR
                const payload = {
                    cid: crypto.randomBytes(4).toString('hex'), // Random 8-char hex
                    time: getTimestamp(),
                    type: "command",
                    cn: "setPort",
                    ct: "mobile",
                    data: {
                        portName: "Control",
                        properties: {
                            "D0310C": value // The magic property for mode
                        }
                    }
                };
                client.publish(ncpTopic, JSON.stringify(payload));
            };

            // --- WEB SERVER ---
            const server = http.createServer((req, res) => {
                const reqUrl = new URL(req.url, `http://${req.headers.host}`);
                const pathname = reqUrl.pathname;
                console.log(`🌐 Web Request: ${pathname}`);

                // Modes based on your HAR capture values: 0, 1, 17, 18
                if (pathname === '/on') {
                    console.log('💡 Power ON');
                    client.publish(shadowTopic, JSON.stringify({ state: { desired: { powerOn: true } } }));
                } else if (pathname === '/off') {
                    console.log('💡 Power OFF');
                    client.publish(shadowTopic, JSON.stringify({ state: { desired: { powerOn: false } } }));
                } else if (pathname === '/auto') {
                    console.log('💡 Mode: Auto (0)');
                    setMode(0);
                } else if (pathname === '/low') {
                    console.log('💡 Mode: Low (17)');
                    setMode(17);
                } else if (pathname === '/medium') {
                    console.log('💡 Mode: Medium (1)');
                    setMode(1);
                } else if (pathname === '/high') {
                    console.log('💡 Mode: High (18)');
                    setMode(18);
                }

                // UI Response
                if (pathname === '/') {
                    res.writeHead(200, { 'Content-Type': 'text/html' });
                    res.end(`
                        <!DOCTYPE html>
                        <html style="font-family: sans-serif; text-align: center; background: #f4f4f4;">
                        <head><title>Air Controller</title></head>
                        <body style="padding: 50px;">
                            <h1>${myDevice.friendlyName}</h1>
                            <div style="background: white; padding: 20px; border-radius: 12px; max-width: 400px; margin: 0 auto; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                                <h2>Power</h2>
                                <div style="display: flex; gap: 10px; justify-content: center; margin-bottom: 20px;">
                                    <a href="/on" style="flex:1; padding: 15px; background: #4CAF50; color: white; text-decoration: none; border-radius: 8px;">ON</a>
                                    <a href="/off" style="flex:1; padding: 15px; background: #f44336; color: white; text-decoration: none; border-radius: 8px;">OFF</a>
                                </div>
                                <h2>Modes</h2>
                                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                                    <a href="/auto" style="padding: 15px; background: #2196F3; color: white; text-decoration: none; border-radius: 8px;">Auto</a>
                                    <a href="/low" style="padding: 15px; background: #607D8B; color: white; text-decoration: none; border-radius: 8px;">Low</a>
                                    <a href="/medium" style="padding: 15px; background: #FF9800; color: white; text-decoration: none; border-radius: 8px;">Medium</a>
                                    <a href="/high" style="padding: 15px; background: #9C27B0; color: white; text-decoration: none; border-radius: 8px;">High</a>
                                </div>
                            </div>
                        </body>
                        </html>
                    `);
                } else {
                    // Simple 204 No Content for commands to keep browser on page
                    res.writeHead(204);
                    res.end();
                }
            });

            server.listen(CONFIG.serverPort, () => {
                console.log(`\n✨ Web Controller running at: http://localhost:${CONFIG.serverPort}`);
            });
        });

        client.on('message', (topic, message) => {
            // Optional: Log feedback from device
            // console.log(`📩 ${topic}: ${message}`);
        });

        client.on('error', (err) => console.error('❌ MQTT Error:', err));
        client.on('close', () => console.log('🔸 MQTT Closed'));

    } catch (error) {
        console.error('❌ Application Error:', error);
    }
}

main();