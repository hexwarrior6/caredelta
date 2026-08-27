import {WorkspaceShell}from"@/components/workspace-shell";
export default async function WorkspacePage({params}:{params:Promise<{patientId:string}>}){const{patientId}=await params;return <WorkspaceShell patientId={patientId}/>}
