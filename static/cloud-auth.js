import {createClient} from './vendor/supabase.js';

function clientFor(config) {
  return createClient(config.supabase_url, config.publishable_key, {
    auth: {flowType:'pkce', persistSession:true, autoRefreshToken:true, detectSessionInUrl:false},
  });
}
function safeNext() {
  const next=new URL(location.href).searchParams.get('next')||'/';
  return next.startsWith('/')&&!next.startsWith('//')&&!next.includes('\\')?next:'/';
}
async function cookie(session) {
  const response=await fetch('/auth/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({access_token:session.access_token})});
  if(!response.ok) throw new Error('로그인을 확인하지 못했습니다. 다시 로그인하세요.');
}
export async function bootstrap(config) {
  const client=clientFor(config);
  const {data:{session}}=await client.auth.getSession();
  if(!session) {location.replace('/login?next='+encodeURIComponent(location.pathname+location.search));await new Promise(()=>{});}
  await cookie(session);
  client.auth.onAuthStateChange((event,session)=>{
    if(event==='TOKEN_REFRESHED'&&session) setTimeout(()=>cookie(session).catch(()=>location.replace('/login')),0);
  });
  document.querySelectorAll('.local-pill').forEach(e=>e.textContent='PRIVATE CLOUD WORKSPACE');
  document.querySelectorAll('.beta').forEach(e=>e.textContent='SHARED');
  const edition=document.querySelector('footer span:last-child');
  if(edition)edition.textContent='v0.2 · Shared edition';
  const bottom=document.querySelector('.rail-bottom');
  bottom.replaceChildren();
  const title=document.createElement('small');title.textContent='내 계정 전용 · 다른 사용자와 분리';
  const signout=document.createElement('button');signout.className='button small';signout.textContent='로그아웃';
  signout.onclick=async()=>{await fetch('/auth/session',{method:'DELETE'});await client.auth.signOut();location.replace('/login');};
  bottom.append(title,document.createElement('br'),signout);
  document.querySelectorAll('.ai-panel').forEach(e=>e.hidden=true);
  const connect=document.getElementById('connect');
  connect.replaceChildren();
  const heading=document.createElement('h1');heading.textContent='친구와 함께 쓰는 ChatGPT 플러그인';
  const text=document.createElement('p');text.textContent='ChatGPT 플러그인에서 사용자 지정 MCP 서버를 추가하고 OAuth로 내 계정을 연결하세요.';
  const code=document.createElement('pre');code.className='code-block';code.textContent=config.mcp_url;
  const copy=document.createElement('button');copy.className='button primary';copy.textContent='MCP 주소 복사';copy.onclick=()=>navigator.clipboard.writeText(config.mcp_url);
  const note=document.createElement('p');note.className='hint';note.textContent='친구에게 이 서버 주소를 공유하세요. 각자 계정으로 로그인하므로 파일은 공유되지 않습니다. 계정 정책에 따라 사용자 지정 MCP 추가가 제한될 수 있습니다. 무료 서버가 잠들었으면 이 페이지를 먼저 연 뒤 다시 연결하세요.';
  connect.append(heading,text,code,copy,note);
}

export async function authPage() {
  const status=document.getElementById('auth-status');
  const showError=e=>status.textContent=e.message||String(e);
  try {
    const config=await fetch('/auth/config',{cache:'no-store'}).then(r=>r.json());
    const client=clientFor(config);
    if(config.github_login) document.getElementById('github-login').hidden=false;
    const params=new URL(location.href).searchParams;
    if(params.has('code')) {
      const {error}=await client.auth.exchangeCodeForSession(params.get('code'));
      if(error) throw error;
      params.delete('code');history.replaceState({},'',location.pathname+'?'+params);
    }
    async function proceed() {
      const {data:{session}}=await client.auth.getSession();
      if(!session)return;
      await cookie(session);
      const authorizationId=params.get('authorization_id');
      if(location.pathname==='/oauth/consent') {
        if(!authorizationId)throw Error('인증 요청 ID가 없습니다. ChatGPT에서 다시 연결하세요.');
        const {data,error}=await client.auth.oauth.getAuthorizationDetails(authorizationId);
        if(error)throw error;
        if(data.redirect_url&&!data.authorization_id) {
          const target=new URL(data.redirect_url);
          if(target.protocol!=='https:')throw Error('보안 연결 주소가 아닙니다.');
          location.assign(target.href);return;
        }
        document.getElementById('login-form').hidden=true;
        document.getElementById('github-login').hidden=true;
        document.getElementById('consent').hidden=false;
        document.getElementById('consent-details').textContent=`요청한 앱: ${data.client?.name||data.client?.client_name||'MCP 클라이언트'}\n요청 범위: ${data.scope||'openid'}`;
        const decide=async(approve)=>{
          const {data,error}=approve?await client.auth.oauth.approveAuthorization(authorizationId,{skipBrowserRedirect:true}):await client.auth.oauth.denyAuthorization(authorizationId,{skipBrowserRedirect:true});
          if(error)throw error;
          // Redirect target is returned by the authorization server, never by a user-supplied next URL.
          const target=new URL(data.redirect_url);
          if(target.protocol!=='https:')throw Error('보안 연결 주소가 아닙니다.');
          location.assign(target.href);
        };
        document.getElementById('approve').onclick=()=>decide(true).catch(showError);
        document.getElementById('deny').onclick=()=>decide(false).catch(showError);
      } else if(location.pathname.startsWith('/download/')) {
        const identifier=location.pathname.split('/').pop();
        if(!/^[a-f0-9]{32}$/.test(identifier))throw Error('잘못된 파일 주소입니다.');
        document.getElementById('login-form').hidden=true;
        document.getElementById('auth-title').textContent='완성된 PDF';
        document.getElementById('auth-description').textContent='본인 계정의 파일을 다운로드합니다.';
        const link=document.createElement('a');link.className='button primary';link.textContent='PDF 다운로드';link.href='/api/exports/'+identifier+'.pdf';link.download='inklab-annotated.pdf';status.replaceChildren(link);
      } else location.replace(safeNext());
    }
    document.getElementById('login-form').onsubmit=async e=>{
      e.preventDefault();status.textContent='로그인 중…';
      try{const {error}=await client.auth.signInWithPassword({email:document.getElementById('email').value,password:document.getElementById('password').value});if(error)throw error;await proceed();}catch(e){showError(e);}
    };
    document.getElementById('signup').onclick=async()=>{
      try{const {data,error}=await client.auth.signUp({email:document.getElementById('email').value,password:document.getElementById('password').value,options:{emailRedirectTo:location.href}});if(error)throw error;if(data.session)await proceed();else status.textContent='확인 메일의 링크를 누른 뒤 다시 로그인하세요.';}catch(e){showError(e);}
    };
    document.getElementById('github-login').onclick=()=>client.auth.signInWithOAuth({provider:'github',options:{redirectTo:location.href}}).then(({error})=>{if(error)showError(error);});
    await proceed();
  }catch(e){showError(e);}
}
