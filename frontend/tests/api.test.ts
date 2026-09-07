import {describe,it,expect,vi} from 'vitest';
import {snapshotSchema,readSnapshot,mutateSession,ApiError,closeSession} from '../src/api';
const snapshot={revision:1,phase:'idle',status:'Ready',speakers:[],entries:[],partial:null,saved:null};
describe('Browser session API contract',()=>{
  it('validates response types and rejects incompatible payloads',()=>{
    expect(snapshotSchema.safeParse(snapshot).success).toBe(true);
    expect(snapshotSchema.safeParse({...snapshot,revision:-1}).success).toBe(false);
    expect(snapshotSchema.safeParse({...snapshot,speakers:{Guest1:'Ana'}}).success).toBe(false);
  });
  it('reads without caching or following redirects',async()=>{
    const fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify(snapshot)));vi.stubGlobal('fetch',fetcher);
    const signal=new AbortController().signal;
    expect(await readSnapshot('session',signal)).toEqual(snapshot);
    expect(fetcher).toHaveBeenCalledWith('/api/ui/sessions/session',expect.objectContaining({signal,cache:'no-store',credentials:'same-origin',redirect:'error'}));
  });
  it('posts one mutation with JSON, request id and cancellation',async()=>{
    const fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify(snapshot)));vi.stubGlobal('fetch',fetcher);
    await mutateSession('session','start',{participant_names:['Ana']},new AbortController().signal);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledWith('/api/ui/sessions/session/start',expect.objectContaining({method:'POST',body:JSON.stringify({participant_names:['Ana']}),headers:expect.objectContaining({'Content-Type':'application/json','X-Request-ID':expect.any(String)})}));
  });
  it('preserves error snapshot and rejects HTML responses',async()=>{
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({title:'Save failed',message:'Try stop again',snapshot}),{status:503})));
    await expect(readSnapshot('s',new AbortController().signal)).rejects.toMatchObject({title:'Save failed',snapshot});
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('<html>Gateway</html>',{status:502})));
    await expect(readSnapshot('s',new AbortController().signal)).rejects.toBeInstanceOf(ApiError);
  });
  it('rejects malformed successful snapshots and never retries a mutation',async()=>{
    const fetcher=vi.fn().mockResolvedValue(new Response('{}'));vi.stubGlobal('fetch',fetcher);
    await expect(mutateSession('s','stop',{},new AbortController().signal)).rejects.toBeInstanceOf(ApiError);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('close requests use keepalive and tolerate transport failure',()=>{
    const fetcher=vi.fn().mockRejectedValue(new Error('offline'));vi.stubGlobal('fetch',fetcher);
    closeSession('s');
    expect(fetcher).toHaveBeenCalledWith('/api/ui/sessions/s/close',expect.objectContaining({method:'POST',keepalive:true}));
  });
});