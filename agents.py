import asyncio  # Para programação assíncrona
import spade
from spade.agent import Agent  # Classe base para criar agentes
from spade.behaviour import OneShotBehaviour, CyclicBehaviour  # Tipos de comportamentos
from spade.message import Message  # Para criar mensagens entre agentes
import warnings
import random
import time
from typing import List, Dict

class HospitalAgent(Agent):
    """
    Agente Hospital:
    - Recebe pedidos de admissão de pacientes
    - Implementa lógica de priorização baseada na severidade
    - Comunica disponibilidade de recursos com outros hospitais
    - Fica sempre ativo esperando mensagens (CyclicBehaviour)
    """

    # Comportamento: Admitir Pacientes
    class AdmitBehaviour(CyclicBehaviour):
        """
        CyclicBehaviour = executa em LOOP INFINITO
        Fica constantemente à espera de mensagens
        """
        
        async def run(self):
            """
            Método run() é chamado repetidamente pelo SPADE
            Fluxo: run() → executa → run() → executa → ...
            """
            
            # Tenta receber uma mensagem (espera até 5 segundos)
            msg = await self.receive(timeout=5)
            
            if msg:
                msg_type = msg.get_metadata("type")
                
                if msg_type == "admission_request":
                    await self.agent._handle_admission_request(msg, self)
                elif msg_type == "resource_query":
                    await self.agent._handle_resource_query(msg, self)
                elif msg_type == "patient_transfer":
                    await self.agent._handle_patient_transfer(msg, self)
                else:
                    # Para mensagens sem tipo específico, tratar como pedido de admissão
                    await self.agent._handle_admission_request(msg, self)
    
    async def _handle_admission_request(self, msg, behaviour):
        """Handle patient admission requests with priority logic"""
        # Verificar se é uma mensagem de consulta de recursos
        if msg.body == "resource_query" or msg.body == "test":
            await self._handle_resource_query(msg, behaviour)
            return
            
        # Tentar parsear dados do paciente
        try:
            patient_data = msg.body.split("|")  # Format: "patient_id|severity|location"
            patient_id = patient_data[0]
            severity = int(patient_data[1]) if len(patient_data) > 1 else 3
            location = patient_data[2] if len(patient_data) > 2 else "unknown"
        except:
            # Se não conseguir parsear, tratar como paciente simples
            patient_id = msg.body
            severity = 3
            location = "unknown"
        
        print(f"[{self.name}] Recebeu pedido: {patient_id} (severidade: {severity})")
        
        reply = Message(to=str(msg.sender))
        
        # Lógica de admissão baseada na severidade e disponibilidade
        if self.beds_available > 0:
            # Aceitar qualquer paciente se há camas disponíveis
            # (em um sistema real, sempre que há cama disponível, o paciente deve ser admitido)
            self.beds_available -= 1
            self.patients.append({
                'id': patient_id,
                'severity': severity,
                'location': location,
                'admission_time': time.time()
            })
            self.patients_treated += 1
            
            reply.body = f"ACCEPTED|{patient_id}|{self.beds_available}|{self.name}"
            reply.set_metadata("status", "accepted")
            
            print(f"[{self.name}] Paciente {patient_id} admitido (severidade {severity})")
            print(f"[{self.name}] Camas: {self.beds_available}/{self.beds_total} disponíveis")
        else:
            reply.body = f"REJECTED|{patient_id}|NO_BEDS|{self.name}"
            reply.set_metadata("status", "rejected")
            self.patients_rejected += 1
            print(f"[{self.name}] Paciente {patient_id} recusado - sem camas")
        
        await behaviour.send(reply)
    
    async def _handle_resource_query(self, msg, behaviour):
        """Handle resource availability queries from other hospitals"""
        reply = Message(to=str(msg.sender))
        reply.set_metadata("type", "resource_response")
        
        resource_info = f"beds:{self.beds_available}/{self.beds_total}|staff:{self.staff_available}|supplies:{self.supplies_available}"
        reply.body = resource_info
        
        await behaviour.send(reply)
    
    async def _handle_patient_transfer(self, msg, behaviour):
        """Handle patient transfer requests from other hospitals"""
        patient_data = msg.body.split("|")
        patient_id = patient_data[0]
        severity = int(patient_data[1]) if len(patient_data) > 1 else 3
        
        reply = Message(to=str(msg.sender))
        
        if self.beds_available > 0:
            self.beds_available -= 1
            self.patients.append({
                'id': patient_id,
                'severity': severity,
                'location': 'transferred',
                'admission_time': time.time()
            })
            
            reply.body = f"TRANSFER_ACCEPTED|{patient_id}|{self.name}"
            reply.set_metadata("status", "accepted")
            print(f"[{self.name}] Transferência aceite para {patient_id}")
        else:
            reply.body = f"TRANSFER_REJECTED|{patient_id}|NO_BEDS|{self.name}"
            reply.set_metadata("status", "rejected")
            print(f"[{self.name}] Transferência rejeitada para {patient_id}")
        
        await behaviour.send(reply)

    # Inicialização do Hospital
    async def setup(self):
        """
        Método setup() é executado UMA VEZ quando o agente inicia
        Aqui configuramos o agente e adicionamos os seus comportamentos
        """
        print(f"[{self.name}] iniciado com {self.beds_total} camas disponíveis.")
        
        # Adiciona o comportamento de admitir pacientes
        # A partir daqui, o run() do AdmitBehaviour começa a executar em loop
        self.add_behaviour(self.AdmitBehaviour())

    def __init__(self, jid, password, beds=2, staff=5, supplies=10):
        """
        Construtor do Hospital
        
        Args:
            jid (str): Jabber ID = identificador único (ex: "hospital@localhost")
            password (str): Password para conectar ao servidor XMPP
            beds (int): Número de camas do hospital (default: 2)
            staff (int): Número de staff disponível (default: 5)
            supplies (int): Nível de supplies disponível (default: 10)
        """
        super().__init__(jid, password)
        
        # Recursos do hospital
        self.beds_total = beds
        self.beds_available = beds
        self.staff_total = staff
        self.staff_available = staff
        self.supplies_total = supplies
        self.supplies_available = supplies
        
        # Lista de pacientes (agora com mais informações)
        self.patients = []
        
        # Métricas de performance
        self.patients_treated = 0
        self.patients_rejected = 0
        self.total_wait_time = 0


class AmbulanceAgent(Agent):
    """
    Agente Ambulância:
    - Implementa lógica inteligente de roteamento de pacientes
    - Consulta disponibilidade de recursos antes de decidir
    - Prioriza pacientes críticos
    - Executa uma vez e termina (OneShotBehaviour)
    """

    # Comportamento: Despachar Pacientes
    class DispatchBehaviour(OneShotBehaviour):
        """
        OneShotBehaviour = executa UMA VEZ e termina
        Ideal para tarefas com início, meio e fim
        """
        
        async def run(self):
            """
            Método run() executa UMA VEZ
            Implementa roteamento inteligente de pacientes
            """
            print(f"[{self.agent.name}] Iniciando processamento de pacientes...")
            
            patients_treated = 0
            patients_rejected = 0
            total_transport_time = 0
            
            # Gera pacientes com diferentes severidades
            patients = self._generate_patients(8)
            print(f"[{self.agent.name}] Gerados {len(patients)} pacientes para processar")
            
            for patient in patients:
                patient_id = patient['id']
                severity = patient['severity']
                location = patient['location']
                
                print(f"\n[{self.agent.name}] Processando {patient_id} (severidade: {severity})")
                
                # Consulta recursos dos hospitais antes de decidir
                hospital_resources = await self._query_hospital_resources()
                
                # Seleciona melhor hospital baseado na severidade e recursos
                best_hospital = self._select_best_hospital(hospital_resources, severity)
                
                if best_hospital:
                    success, transport_time = await self._dispatch_patient(
                        patient_id, severity, location, best_hospital
                    )
                    
                    if success:
                        patients_treated += 1
                        total_transport_time += transport_time
                        print(f"[{self.agent.name}] {patient_id} admitido em {best_hospital}")
                    else:
                        patients_rejected += 1
                        print(f"[{self.agent.name}] {patient_id} NÃO FOI ADMITIDO")
                else:
                    patients_rejected += 1
                    print(f"[{self.agent.name}] {patient_id} NÃO FOI ADMITIDO - nenhum hospital disponível")
                
                await asyncio.sleep(0.5)  # Simula tempo de transporte
            
            # Estatísticas finais
            total_patients = patients_treated + patients_rejected
            if patients_treated > 0:
                avg_transport_time = total_transport_time / patients_treated
            else:
                avg_transport_time = 0
                
            print(f"\n[{self.agent.name}] ESTATÍSTICAS FINAIS:")
            print(f" Pacientes tratados: {patients_treated}")
            print(f" Pacientes rejeitados: {patients_rejected}")
            print(f" Tempo médio de transporte: {avg_transport_time:.2f}s")
            
            if total_patients > 0:
                success_rate = (patients_treated / total_patients) * 100
                print(f" Taxa de sucesso: {success_rate:.1f}%")
            else:
                print(f" Taxa de sucesso: N/A")
        
        def _generate_patients(self, num_patients):
            """Generate patients with different severities and locations"""
            patients = []
            for i in range(num_patients):
                severity = random.choice([1, 1, 2, 2, 3, 3, 3, 4, 4, 5])  # More critical patients
                location = random.choice(["north", "south", "east", "west", "center"])
                patients.append({
                    'id': f"P{i+1}",
                    'severity': severity,
                    'location': location
                })
            return patients
        
        async def _query_hospital_resources(self):
            """Query all hospitals for their current resource availability"""
            resources = {}
            print(f"[{self.agent.name}] Consultando recursos de {len(self.agent.hospital_list)} hospitais...")
            
            for hospital_jid in self.agent.hospital_list:
                print(f"[{self.agent.name}] Enviando consulta de recursos para {hospital_jid}")
                
                msg = Message(to=hospital_jid)
                # Remover metadata para simplificar routing
                msg.body = "resource_query"
                
                await self.send(msg)
                
                reply = await self.receive(timeout=5)
                if reply and reply.body and reply.body != "resource_query":
                    try:
                        # Parse resource info: "beds:2/5|staff:3|supplies:8"
                        resource_data = {}
                        for item in reply.body.split("|"):
                            if ":" in item:
                                key, value = item.split(":", 1)
                                if "/" in value:
                                    available, total = value.split("/")
                                    resource_data[key] = {
                                        'available': int(available),
                                        'total': int(total)
                                    }
                                else:
                                    resource_data[key] = int(value)
                        
                        resources[hospital_jid] = resource_data
                        print(f"[{self.agent.name}] Recursos de {hospital_jid}: {resource_data}")
                    except Exception as e:
                        print(f"[{self.agent.name}] Erro ao parsear recursos de {hospital_jid}: {e}")
                else:
                    print(f"[{self.agent.name}] Não foi possível obter recursos de {hospital_jid} (timeout ou resposta inválida)")
            
            print(f"[{self.agent.name}] Consulta concluída. Recursos obtidos de {len(resources)} hospitais")
            return resources
        
        def _select_best_hospital(self, resources, severity):
            """Select the best hospital based on patient severity and available resources"""
            print(f"[{self.agent.name}] Selecionando melhor hospital para severidade {severity}")
            print(f"[{self.agent.name}] Recursos disponíveis: {resources}")
            
            if not resources:
                print(f"[{self.agent.name}] Nenhum recurso disponível!")
                return None
            
            # Para pacientes críticos (severidade 1-2), priorizar hospitais com mais recursos
            if severity <= 2:
                best_hospital = max(resources.keys(), key=lambda h: 
                    resources[h].get('beds', {}).get('available', 0) * 3 +
                    resources[h].get('staff', 0) * 2 +
                    resources[h].get('supplies', 0)
                )
                print(f"[{self.agent.name}] Paciente crítico - selecionado hospital com mais recursos: {best_hospital}")
            else:
                # Para pacientes menos críticos, escolher qualquer hospital com camas
                available_hospitals = [h for h, r in resources.items() 
                                     if r.get('beds', {}).get('available', 0) > 0]
                print(f"[{self.agent.name}] Hospitais com camas disponíveis: {available_hospitals}")
                
                if available_hospitals:
                    best_hospital = random.choice(available_hospitals)
                    print(f"[{self.agent.name}] Selecionado hospital aleatório: {best_hospital}")
                else:
                    print(f"[{self.agent.name}] Nenhum hospital com camas disponíveis!")
                    return None
            
            return best_hospital
        
        async def _dispatch_patient(self, patient_id, severity, location, hospital_jid, tried_hospitals=None):
            """Dispatch patient to selected hospital"""
            if tried_hospitals is None:
                tried_hospitals = []
                
            msg = Message(to=hospital_jid)
            # Remover metadata para simplificar routing
            msg.body = f"{patient_id}|{severity}|{location}"
            
            start_time = time.time()
            await self.send(msg)
            print(f"[{self.agent.name}] Enviando {patient_id} para {hospital_jid}")
            
            reply = await self.receive(timeout=5)
            transport_time = time.time() - start_time
            
            if reply:
                print(f"[{self.agent.name}] Resposta de {hospital_jid}: {reply.body}")
                
                # Verificar se foi aceite baseado no conteúdo da mensagem
                if "ACCEPTED" in reply.body or "aceite" in reply.body.lower():
                    return True, transport_time
                else:
                    # Se rejeitado, tenta outros hospitais
                    return await self._try_other_hospitals(patient_id, severity, location, tried_hospitals + [hospital_jid])
            else:
                print(f"[{self.agent.name}] TIMEOUT de {hospital_jid}")
                return False, transport_time
        
        async def _try_other_hospitals(self, patient_id, severity, location, tried_hospitals):
            """Try other hospitals if the first choice rejects the patient"""
            remaining_hospitals = [h for h in self.agent.hospital_list if h not in tried_hospitals]
            
            for hospital_jid in remaining_hospitals:
                # Enviar mensagem diretamente sem recursão
                msg = Message(to=hospital_jid)
                msg.body = f"{patient_id}|{severity}|{location}"
                
                start_time = time.time()
                await self.send(msg)
                print(f"[{self.agent.name}] Enviando {patient_id} para {hospital_jid} (fallback)")
                
                reply = await self.receive(timeout=5)
                transport_time = time.time() - start_time
                
                if reply:
                    print(f"[{self.agent.name}] Resposta de {hospital_jid}: {reply.body}")
                    
                    if "ACCEPTED" in reply.body or "aceite" in reply.body.lower():
                        return True, transport_time
                
                tried_hospitals.append(hospital_jid)
            
            return False, 0

        # Método chamado quando o behaviour termina
        async def on_end(self):
            """
            on_end() é executado automaticamente quando run() termina
            Aqui paramos o agente ambulância
            """
            await self.agent.stop()  # Para o agente
            print(f"[{self.agent.name}] Terminou o trabalho e desligou.")
    
    def __init__(self, jid, password, hospital_list=None):
        super().__init__(jid, password)
        self.hospital_list = hospital_list or []
        
        # Métricas de performance da ambulância
        self.total_patients_processed = 0
        self.successful_transports = 0
        self.failed_transports = 0
        self.total_transport_time = 0
    
    # Inicialização da Ambulância
    async def setup(self):
        """
        Método setup() executado UMA VEZ quando o agente inicia
        """
        print(f"[{self.name}] 🚑 AMBULÂNCIA INICIADA! Hospitais disponíveis: {self.hospital_list}")
        
        # Cria e adiciona o comportamento de despacho
        b = self.DispatchBehaviour()
        self.add_behaviour(b)
        print(f"[{self.name}] Comportamento de despacho adicionado - iniciando processamento...")
        # Como é OneShotBehaviour, o run() executará UMA VEZ


async def main():
    warnings.filterwarnings("ignore")
    """
    Função principal que:
    1. Cria os agentes com configurações realistas
    2. Inicia-os
    3. Aguarda execução
    4. Gera relatório detalhado de performance
    """
    
    print("=" * 60)
    print("🏥 SISTEMA MULTI-AGENTE DE GESTÃO HOSPITALAR")
    print("📋 Simulação de Alocação de Recursos e Emergências")
    print("=" * 60)
    
    # ------------------------------------------------------------------------
    # 1. CRIAR OS AGENTES COM CONFIGURAÇÕES REALISTAS
    # ------------------------------------------------------------------------
    
    # Hospitais com diferentes capacidades e recursos
    hospital1 = HospitalAgent("hospital1@localhost", "pass", beds=5, staff=8, supplies=15)  # Hospital grande
    hospital2 = HospitalAgent("hospital2@localhost", "pass", beds=3, staff=5, supplies=10)  # Hospital médio
    hospital3 = HospitalAgent("hospital3@localhost", "pass", beds=2, staff=3, supplies=8)   # Hospital pequeno
    
    hospital_jids = [
        "hospital1@localhost",
        "hospital2@localhost", 
        "hospital3@localhost"
    ]
    
    # Ambulâncias com diferentes estratégias
    ambulance1 = AmbulanceAgent("ambulance1@localhost", "pass", hospital_list=hospital_jids)
    ambulance2 = AmbulanceAgent("ambulance2@localhost", "pass", hospital_list=hospital_jids)
    
    # ------------------------------------------------------------------------
    # 2. INICIAR OS AGENTES
    # ------------------------------------------------------------------------
    
    print("\n🚀 Iniciando rede hospitalar...")
    print("📊 Configuração dos Hospitais:")
    print(f"   • Hospital 1: {hospital1.beds_total} camas, {hospital1.staff_total} staff, {hospital1.supplies_total} supplies")
    print(f"   • Hospital 2: {hospital2.beds_total} camas, {hospital2.staff_total} staff, {hospital2.supplies_total} supplies")
    print(f"   • Hospital 3: {hospital3.beds_total} camas, {hospital3.staff_total} staff, {hospital3.supplies_total} supplies")
    print(f"   • Ambulâncias: {len([ambulance1, ambulance2])} ativas")
    
    await hospital1.start(auto_register=True)
    await hospital2.start(auto_register=True)
    await hospital3.start(auto_register=True)
    
    await asyncio.sleep(2)  # Dar tempo aos hospitais iniciarem
    
    await ambulance1.start(auto_register=True)
    await ambulance2.start(auto_register=True)
    
    print("\n✅ Todos os agentes iniciados com sucesso!")
    print("🏃‍♂️ Simulação em andamento...\n")
    
    # ------------------------------------------------------------------------
    # 3. AGUARDAR EXECUÇÃO
    # ------------------------------------------------------------------------
    
    await asyncio.sleep(30)  # Tempo suficiente para processar todos os pacientes
    
    # ------------------------------------------------------------------------
    # 4. RELATÓRIO FINAL DETALHADO
    # ------------------------------------------------------------------------
    
    print("\n" + "=" * 60)
    print("📊 RELATÓRIO FINAL DO SISTEMA")
    print("=" * 60)
    
    # Estatísticas por hospital
    total_patients_treated = 0
    total_patients_rejected = 0
    
    hospitals = [hospital1, hospital2, hospital3]
    for i, hospital in enumerate(hospitals, 1):
        print(f"\n🏥 HOSPITAL {i} ({hospital.name}):")
        print(f"   📋 Pacientes admitidos: {hospital.patients_treated}")
        print(f"   ❌ Pacientes rejeitados: {hospital.patients_rejected}")
        print(f"   🛏️  Camas: {hospital.beds_available}/{hospital.beds_total} disponíveis")
        print(f"   👥 Staff: {hospital.staff_available}/{hospital.staff_total} disponível")
        print(f"   📦 Supplies: {hospital.supplies_available}/{hospital.supplies_total} disponível")
        
        if hospital.patients:
            print(f"   👤 Pacientes atuais:")
            for patient in hospital.patients:
                severity_text = ["CRÍTICO", "URGENTE", "MÉDIO", "BAIXO", "MÍNIMO"][patient['severity']-1]
                print(f"      • {patient['id']} (severidade {patient['severity']} - {severity_text})")
        
        total_patients_treated += hospital.patients_treated
        total_patients_rejected += hospital.patients_rejected
    
    # Métricas globais
    print(f"\n📈 MÉTRICAS GLOBAIS:")
    print(f"   ✅ Total de pacientes tratados: {total_patients_treated}")
    print(f"   ❌ Total de pacientes rejeitados: {total_patients_rejected}")
    
    total_patients = total_patients_treated + total_patients_rejected
    if total_patients > 0:
        success_rate = (total_patients_treated / total_patients) * 100
        print(f"   📊 Taxa de sucesso global: {success_rate:.1f}%")
    else:
        print(f"   📊 Taxa de sucesso global: N/A (nenhum paciente processado)")
    
    # Utilização de recursos
    total_beds = sum(h.beds_total for h in hospitals)
    total_available_beds = sum(h.beds_available for h in hospitals)
    beds_utilization = ((total_beds - total_available_beds) / total_beds) * 100
    
    print(f"   🛏️  Utilização de camas: {beds_utilization:.1f}%")
    
    # Limpar recursos
    await hospital1.stop()
    await hospital2.stop()
    await hospital3.stop()
    
    print("\n🏁 Simulação terminada com sucesso!")
    print("=" * 60)


if __name__ == "__main__":
    spade.run(main(), embedded_xmpp_server=True)