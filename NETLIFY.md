# Netlify par deploy

Is project ki live website `www/` folder me hai. Root `netlify.toml` Netlify ko isi folder se site publish karne ke liye configure karta hai; build command ki zaroorat nahi hai.

## GitHub se deploy

1. Project ko GitHub repository me push karein.
2. Netlify me **Add new site > Import an existing project** chunein aur repository connect karein.
3. Build settings me publish directory `www` rakhein. Build command khaali chhodein.
4. **Deploy site** chunein. `netlify.toml` ye publish setting apne aap set karta hai.

## Manual deploy

Netlify ke manual deploy me `www/` folder upload karein. Is folder ke andar `index.html`, baaki pages, CSS, JavaScript aur images maujood hain.

`backend/app.py` ek alag Flask server hai. Netlify par static site deploy karne se Flask server run nahi hota; filhaal website ko serve karne ke liye uski zaroorat nahi hai.
