import React from 'react';
import {it,expect,vi} from 'vitest';
import {render,screen,fireEvent,waitFor,within} from '@testing-library/react';
import App from '../src/App';
it('renders transcript text literally and drives start, rename and stop controls',async()=>{
  let state={revision:1,phase:'idle',status:'Ready',speakers:[],entries:[],partial:null,saved:null} as any;
  const fetcher=vi.fn(async(input:string,init?:RequestInit)=>{
    if(input.endsWith('/start'))state={...state,revision:2,phase:'recording',speakers:[{id:'Guest-1',name:'Ana'}],entries:[{time:'10:00:00',speaker_id:'Guest-1',speaker:'Ana',text:'<img src=x onerror=alert(1)>'}]};
    if(input.endsWith('/rename')){const body=JSON.parse(String(init?.body));state={...state,revision:3,speakers:[{id:'Guest-1',name:body.new_name}],entries:state.entries.map((entry:any)=>({...entry,speaker:body.new_name}))};}
    if(input.endsWith('/stop'))state={...state,revision:4,phase:'stopped',saved:{json_path:'transcripts/session.json',txt_path:'transcripts/session.txt'}};
    return new Response(JSON.stringify(state));
  });
  vi.stubGlobal('fetch',fetcher);const {container}=render(<App/>);
  const start=screen.getByRole('button',{name:/Pornește/});await waitFor(()=>expect((start as HTMLButtonElement).disabled).toBe(false));
  fireEvent.change(screen.getByLabelText(/Participanți/),{target:{value:'Ana, Mihai'}});fireEvent.click(start);
  await within(screen.getByRole('region',{name:'Transcriere; text doar pentru citire'})).findByText('<img src=x onerror=alert(1)>',{exact:false});expect(container.querySelector('img')).toBeNull();
  expect((start as HTMLButtonElement).disabled).toBe(true);
  const rename=screen.getByRole('form',{name:'Redenumește vorbitor'});
  const nameInput=rename.querySelector('input')!;fireEvent.change(nameInput,{target:{value:'Maria'}});fireEvent.submit(rename);
  await waitFor(()=>expect(container.textContent).toContain('Maria:'));
  fireEvent.click(screen.getByRole('button',{name:/Oprește și salvează/}));
  await waitFor(()=>expect((start as HTMLButtonElement).disabled).toBe(false));
  expect(fetcher.mock.calls.filter(([url])=>url.endsWith('/start'))).toHaveLength(1);
  expect(fetcher.mock.calls.filter(([url])=>url.endsWith('/stop'))).toHaveLength(1);
});
it('connection failures never show fake recording or enable start',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new Error('offline')));render(<App/>);
  await screen.findByText('Conexiune indisponibilă');
  expect((screen.getByRole('button',{name:/Pornește/}) as HTMLButtonElement).disabled).toBe(true);
});