import asyncio  # Para programação assíncrona
import spade
from spade.agent import Agent  # Classe base para criar agentes
from spade.behaviour import OneShotBehaviour, CyclicBehaviour  # Tipos de comportamentos
from spade.message import Message  # Para criar mensagens entre agentes
import warnings
import random
import time
from typing import List, Dict
from dataclasses import dataclass

# -----------------------------
# Configurações Globais
# -----------------------------
SIMULATION_DURATION = 60  # segundos de simulação activa
RESOURCE_RECOVERY_INTERVAL = 2  # segundos entre verificações de alta
EMERGENCY_PROBABILITY = 0.18  # probabilidade de paciente ser emergência
MASS_EVENT_PROBABILITY = 0.07  # probabilidade de gerar evento em massa
MASS_EVENT_SIZE = (3, 6)  # intervalo de nº de pacientes em eventos em massa

MAX_RETRY_ATTEMPTS = 4
RETRY_DELAY_SECONDS = 1.0
TRAVEL_TIME_RANGE = (1.0, 3.0)  # segundos de deslocação simulada
RETRYABLE_REASONS = {"NO_BEDS", "NO_STAFF", "NO_SUPPLIES", "TIMEOUT", "NO_HOSPITAL"}

PATIENT_PROFILES = {
    "emergency": {
        "staff": 2,
        "supplies": 3,
        "length_of_stay": 12,  # segundos em simulação
    },
    "routine": {
        "staff": 1,
        "supplies": 1,
        "length_of_stay": 8,
    },
}

SEVERITY_LABELS = {
    1: "CRÍTICO",
    2: "URGENTE",
    3: "MÉDIO",
    4: "BAIXO",
    5: "MÍNIMO",
}

@dataclass
class PatientRecord:
    id: str
    severity: int
    location: str
    patient_type: str
    admission_time: float
    length_of_stay: float

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
        """Handle patient admission requests with priority and resource checks"""
        # Verificar mensagens especiais (ex: query)
        if msg.body in {"resource_query", "test"}:
            await self._handle_resource_query(msg, behaviour)
            return

        patient_id, severity, location, patient_type = self._parse_patient_message(msg)

        admitted, reason = self._attempt_admission(patient_id, severity, location, patient_type)

        reply = Message(to=str(msg.sender))
        reply.set_metadata("status", "accepted" if admitted else "rejected")

        if admitted:
            reply.body = f"ACCEPTED|{patient_id}|{self.beds_available}|{self.name}|{patient_type}"
        else:
            reply.body = f"REJECTED|{patient_id}|{reason}|{self.name}|{patient_type}"
            self.patients_rejected += 1
            self.patients_rejected_by_reason[reason] = self.patients_rejected_by_reason.get(reason, 0) + 1

        await behaviour.send(reply)

    async def _handle_resource_query(self, msg, behaviour):
        """Handle resource availability queries from other hospitals"""
        reply = Message(to=str(msg.sender))
        reply.set_metadata("type", "resource_response")

        occupancy = (self.beds_total - self.beds_available) / max(1, self.beds_total)
        resource_info = (
            f"beds:{self.beds_available}/{self.beds_total}"
            f"|staff:{self.staff_available}/{self.staff_total}"
            f"|supplies:{self.supplies_available}/{self.supplies_total}"
            f"|occupancy:{occupancy:.2f}"
        )
        reply.body = resource_info

        await behaviour.send(reply)

    async def _handle_patient_transfer(self, msg, behaviour):
        """Handle patient transfer requests from other hospitals"""
        patient_id, severity, location, patient_type = self._parse_patient_message(msg, default_location="transferred")

        admitted, reason = self._attempt_admission(patient_id, severity, location, patient_type)

        reply = Message(to=str(msg.sender))
        reply.set_metadata("status", "accepted" if admitted else "rejected")

        if admitted:
            reply.body = f"TRANSFER_ACCEPTED|{patient_id}|{self.name}|{patient_type}"
        else:
            reply.body = f"TRANSFER_REJECTED|{patient_id}|{reason}|{self.name}|{patient_type}"
            self.patients_rejected += 1
            self.patients_rejected_by_reason[reason] = self.patients_rejected_by_reason.get(reason, 0) + 1

        await behaviour.send(reply)

    class ResourceRecoveryBehaviour(CyclicBehaviour):
        async def run(self):
            await asyncio.sleep(RESOURCE_RECOVERY_INTERVAL)

            if not self.agent.patients:
                return

            now = time.time()
            discharged_patients = []

            for patient in list(self.agent.patients):
                if now - patient.admission_time >= patient.length_of_stay:
                    profile = PATIENT_PROFILES.get(patient.patient_type, PATIENT_PROFILES["routine"])

                    stay_duration = now - patient.admission_time

                    # Libertar recursos
                    self.agent.beds_available = min(self.agent.beds_total, self.agent.beds_available + 1)
                    self.agent.staff_available = min(
                        self.agent.staff_total, self.agent.staff_available + profile["staff"]
                    )
                    self.agent.supplies_available = min(
                        self.agent.supplies_total, self.agent.supplies_available + profile["supplies"]
                    )

                    self.agent.patients.remove(patient)
                    self.agent.patients_discharged += 1
                    self.agent.total_discharge_time += stay_duration
                    discharged_patients.append(patient.id)

            if discharged_patients:
                self.agent._log_resource_snapshot(
                    event="discharge",
                    details={"released": ",".join(discharged_patients)},
                )
                print(
                    f"[{self.agent.name}] Altas realizadas: {discharged_patients} | "
                    f"Camas {self.agent.beds_available}/{self.agent.beds_total}"
                )

    # Inicialização do Hospital
    async def setup(self):
        """
        Método setup() é executado UMA VEZ quando o agente inicia
        Aqui configuramos o agente e adicionamos os seus comportamentos
        """
        print(f"[{self.name}] iniciado com {self.beds_total} camas disponíveis.")
        
        # Adiciona comportamentos principais
        self.add_behaviour(self.AdmitBehaviour())
        self.add_behaviour(self.ResourceRecoveryBehaviour())

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

        # Lista de pacientes internados (PatientRecord)
        self.patients: List[PatientRecord] = []

        # Métricas de performance
        self.patients_treated = 0
        self.patients_rejected = 0
        self.patients_discharged = 0
        self.total_discharge_time = 0.0
        self.patients_treated_by_type: Dict[str, int] = {"emergency": 0, "routine": 0}
        self.patients_rejected_by_reason: Dict[str, int] = {}

        # Histórico de recursos ao longo da simulação
        self.resource_history = []

    def _parse_patient_message(self, msg, default_location="unknown"):
        parts = msg.body.split("|") if msg.body else []
        patient_id = parts[0] if parts else "UNKNOWN"

        try:
            severity = int(parts[1]) if len(parts) > 1 else 3
        except ValueError:
            severity = 3

        location = parts[2] if len(parts) > 2 and parts[2] else default_location
        patient_type = parts[3] if len(parts) > 3 else ("emergency" if severity <= 2 else "routine")

        return patient_id, severity, location, patient_type

    def _check_resources(self, profile):
        if self.beds_available <= 0:
            return False, "NO_BEDS"
        if self.staff_available < profile["staff"]:
            return False, "NO_STAFF"
        if self.supplies_available < profile["supplies"]:
            return False, "NO_SUPPLIES"
        return True, "OK"

    def _attempt_admission(self, patient_id, severity, location, patient_type):
        profile = PATIENT_PROFILES.get(patient_type, PATIENT_PROFILES["routine"])
        can_admit, reason = self._check_resources(profile)

        if not can_admit:
            print(f"[{self.name}] Paciente {patient_id} recusado - motivo: {reason}")
            return False, reason

        # Consumir recursos
        self.beds_available -= 1
        self.staff_available -= profile["staff"]
        self.supplies_available -= profile["supplies"]

        record = PatientRecord(
            id=patient_id,
            severity=severity,
            location=location,
            patient_type=patient_type,
            admission_time=time.time(),
            length_of_stay=profile["length_of_stay"],
        )
        self.patients.append(record)

        # Atualizar métricas
        self.patients_treated += 1
        self.patients_treated_by_type[patient_type] = self.patients_treated_by_type.get(patient_type, 0) + 1
        self._log_resource_snapshot(event="admission", details={"patient": patient_id, "type": patient_type})

        severity_label = SEVERITY_LABELS.get(severity, f"NIVEL-{severity}")
        print(
            f"[{self.name}] Paciente {patient_id} admitido ({severity_label}) | "
            f"Camas {self.beds_available}/{self.beds_total} | "
            f"Staff {self.staff_available}/{self.staff_total} | "
            f"Supplies {self.supplies_available}/{self.supplies_total}"
        )

        return True, "OK"

    def _log_resource_snapshot(self, event, details=None):
        snapshot = {
            "timestamp": time.time(),
            "event": event,
            "beds_available": self.beds_available,
            "staff_available": self.staff_available,
            "supplies_available": self.supplies_available,
            "patients": len(self.patients),
        }
        if details:
            snapshot.update({f"detail_{k}": v for k, v in details.items()})
        self.resource_history.append(snapshot)


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
        """Comportamento responsável por gerar e encaminhar pacientes continuamente."""
        
        async def run(self):
            print(f"[{self.agent.name}] Iniciando processamento de pacientes (Week 4)...")
            patients_treated = 0
            patients_rejected = 0
            total_transport_time = 0.0

            pending_patients = []

            while True:
                current_time = time.time()
                simulation_active = current_time < self.agent.simulation_end

                # Seleciona paciente pendente pronto para nova tentativa
                ready_patient = None
                for idx, candidate in enumerate(pending_patients):
                    if candidate["next_attempt"] <= current_time:
                        ready_patient = pending_patients.pop(idx)
                        break

                patients_batch = []

                if ready_patient:
                    patients_batch.append(ready_patient)
                elif simulation_active:
                    # Determinar se ocorre evento em massa
                    if random.random() < MASS_EVENT_PROBABILITY:
                        event_size = random.randint(*MASS_EVENT_SIZE)
                        self.agent.mass_events_triggered += 1
                        print(f"[{self.agent.name}] 🚨 Evento em massa detectado! {event_size} pacientes gerados")
                        for _ in range(event_size):
                            patients_batch.append(self._generate_patient(force_type="emergency", mass_event=True))
                    else:
                        patients_batch.append(self._generate_patient())
                else:
                    if pending_patients:
                        await asyncio.sleep(0.3)
                        continue
                    break

                for patient in patients_batch:
                    severity_label = SEVERITY_LABELS.get(patient["severity"], str(patient["severity"]))
                    print(
                        f"\n[{self.agent.name}] Processando {patient['id']} (tipo: {patient['type']} | severidade: {severity_label})"
                    )

                    success, transport_time, rejection_reason = await self._process_patient(patient)

                    self.agent.total_patients_processed += 1
                    self.agent.generated_by_type[patient["type"]] = self.agent.generated_by_type.get(patient["type"], 0) + 1

                    if success:
                        patients_treated += 1
                        self.agent.successful_transports += 1
                        if transport_time:
                            total_transport_time += transport_time
                            self.agent.total_transport_time += transport_time
                        if patient["retries"] > 0:
                            self.agent.retry_queue_stats["fulfilled"] += 1
                        continue

                    # avaliar reencaminhamento
                    rejection_reason = rejection_reason or "REJECTED"
                    should_retry = (
                        rejection_reason in RETRYABLE_REASONS
                        and patient["retries"] < MAX_RETRY_ATTEMPTS
                        and time.time() + RETRY_DELAY_SECONDS < self.agent.simulation_end + 2
                    )

                    if should_retry:
                        patient["retries"] += 1
                        patient["next_attempt"] = time.time() + RETRY_DELAY_SECONDS * patient["retries"]

                        # Escalar prioridade em cada tentativa
                        if patient["type"] == "routine" and patient["severity"] > 2:
                            patient["severity"] -= 1
                            if patient["severity"] <= 2:
                                patient["type"] = "emergency"

                        pending_patients.append(patient)
                        self.agent.retry_queue_stats["requeued"] += 1
                        print(
                            f"[{self.agent.name}] {patient['id']} reagendado (tentativa {patient['retries']} / {MAX_RETRY_ATTEMPTS})"
                        )
                        continue

                    patients_rejected += 1
                    self.agent.failed_transports += 1
                    self.agent.rejections_by_reason[rejection_reason] = (
                        self.agent.rejections_by_reason.get(rejection_reason, 0) + 1
                    )

                    await asyncio.sleep(0.3)

                await asyncio.sleep(random.uniform(0.4, 1.2))

            total_patients = max(1, patients_treated + patients_rejected)
            avg_transport_time = total_transport_time / max(1, patients_treated)
            success_rate = (patients_treated / total_patients) * 100

            self.agent.behaviour_summary = {
                "patients_treated": patients_treated,
                "patients_rejected": patients_rejected,
                "avg_transport_time": avg_transport_time,
                "success_rate": success_rate,
            }

            print(f"\n[{self.agent.name}] ESTATÍSTICAS FINAIS:")
            print(f" Pacientes tratados: {patients_treated}")
            print(f" Pacientes rejeitados: {patients_rejected}")
            print(f" Tempo médio de transporte: {avg_transport_time:.2f}s")
            print(f" Taxa de sucesso: {success_rate:.1f}%")

        def _generate_patient(self, force_type=None, mass_event=False):
            patient_type = force_type or ("emergency" if random.random() < EMERGENCY_PROBABILITY else "routine")
            severity_pool = [1, 1, 2, 2, 3] if patient_type == "emergency" else [2, 3, 3, 4, 5]
            severity = random.choice(severity_pool)
            location = random.choice(["norte", "sul", "este", "oeste", "centro"])

            self.agent.patient_counter += 1
            patient_id = f"{self.agent.name.split('@')[0].upper()}_{self.agent.patient_counter:04d}"

            return {
                "id": patient_id,
                "severity": severity,
                "location": location,
                "type": patient_type,
                "mass_event": mass_event,
                "retries": 0,
                "next_attempt": time.time(),
            }

        async def _process_patient(self, patient):
            hospital_resources = await self._query_hospital_resources()
            best_hospital = self._select_best_hospital(hospital_resources, patient)

            if not best_hospital:
                print(f"[{self.agent.name}] Nenhum hospital com recursos suficientes para {patient['id']}")
                return False, 0.0, "NO_HOSPITAL"

            tried_hospitals = [best_hospital]
            success, transport_time, rejection_reason = await self._dispatch_patient(patient, best_hospital)

            if success:
                return True, transport_time, None

            # fallback
            success, transport_time, rejection_reason = await self._try_other_hospitals(
                patient, tried_hospitals, last_reason=rejection_reason
            )
            return success, transport_time, rejection_reason

        async def _query_hospital_resources(self):
            """Query all hospitals for their current resource availability"""
            resources = {}
            print(f"[{self.agent.name}] Consultando recursos de {len(self.agent.hospital_list)} hospitais...")

            for hospital_jid in self.agent.hospital_list:
                msg = Message(to=hospital_jid)
                msg.body = "resource_query"
                await self.send(msg)

                reply = await self.receive(timeout=5)
                if reply and reply.body and reply.body != "resource_query":
                    try:
                        resource_data = {}
                        for item in reply.body.split("|"):
                            if ":" not in item:
                                continue
                            key, value = item.split(":", 1)
                            if "/" in value:
                                available, total = value.split("/")
                                resource_data[f"{key}_available"] = float(available)
                                resource_data[f"{key}_total"] = float(total)
                            else:
                                resource_data[key] = float(value)
                        resources[hospital_jid] = resource_data
                    except Exception as exc:
                        print(f"[{self.agent.name}] Erro ao parsear recursos de {hospital_jid}: {exc}")
                else:
                    print(f"[{self.agent.name}] Não foi possível obter recursos de {hospital_jid}")

            return resources

        def _select_best_hospital(self, resources, patient):
            """Seleciona o hospital mais adequado tendo em conta recursos e severidade."""
            if not resources:
                return None

            profile = PATIENT_PROFILES.get(patient["type"], PATIENT_PROFILES["routine"])

            candidates = []
            for hospital, data in resources.items():
                beds_available = data.get("beds_available", 0)
                staff_available = data.get("staff_available", 0)
                supplies_available = data.get("supplies_available", 0)

                if (
                    beds_available < 1
                    or staff_available < profile["staff"]
                    or supplies_available < profile["supplies"]
                ):
                    continue

                occupancy_penalty = data.get("occupancy", 0.0)
                severity_weight = 2 if patient["severity"] <= 2 or patient["type"] == "emergency" else 1
                score = (
                    beds_available * 3
                    + staff_available * 2
                    + supplies_available
                    - occupancy_penalty * 10
                ) * severity_weight
                candidates.append((score, hospital))

            if not candidates:
                return None

            candidates.sort(reverse=True)
            best_hospital = candidates[0][1]
            print(f"[{self.agent.name}] Hospital selecionado: {best_hospital} (score={candidates[0][0]:.2f})")
            return best_hospital

        async def _dispatch_patient(self, patient, hospital_jid):
            """Despacha o paciente para o hospital indicado."""
            msg = Message(to=hospital_jid)
            msg.set_metadata("type", "admission_request")
            msg.body = f"{patient['id']}|{patient['severity']}|{patient['location']}|{patient['type']}"

            travel_time = random.uniform(*TRAVEL_TIME_RANGE)

            start_time = time.time()
            await self.send(msg)
            print(f"[{self.agent.name}] Enviando {patient['id']} para {hospital_jid}")

            await asyncio.sleep(travel_time)

            reply = await self.receive(timeout=6)
            transport_time = time.time() - start_time

            if not reply:
                print(f"[{self.agent.name}] TIMEOUT de {hospital_jid}")
                return False, transport_time, "TIMEOUT"

            status_meta = reply.get_metadata("status")
            print(f"[{self.agent.name}] Resposta de {hospital_jid}: {reply.body}")

            if status_meta == "accepted" or (reply.body and "ACCEPTED" in reply.body):
                return True, transport_time, None

            reason = None
            if reply.body:
                parts = reply.body.split("|")
                reason = parts[2] if len(parts) > 2 else "REJECTED"

            return False, transport_time, reason or "REJECTED"

        async def _try_other_hospitals(self, patient, tried_hospitals, last_reason=None):
            """Tenta outros hospitais que ainda não foram contactados."""
            remaining = [h for h in self.agent.hospital_list if h not in tried_hospitals]
            rejection_reason = last_reason

            for hospital_jid in remaining:
                success, transport_time, rejection_reason = await self._dispatch_patient(patient, hospital_jid)
                tried_hospitals.append(hospital_jid)
                if success:
                    return True, transport_time, None

            return False, 0.0, rejection_reason

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
        self.generated_by_type = {"emergency": 0, "routine": 0}
        self.rejections_by_reason: Dict[str, int] = {}
        self.mass_events_triggered = 0
        self.patient_counter = 0
        self.retry_queue_stats = {"requeued": 0, "fulfilled": 0}
        self.behaviour_summary = {}
    
    # Inicialização da Ambulância
    async def setup(self):
        """
        Método setup() executado UMA VEZ quando o agente inicia
        """
        print(f"[{self.name}] 🚑 AMBULÂNCIA INICIADA! Hospitais disponíveis: {self.hospital_list}")

        # Configura janela temporal da simulação
        self.simulation_end = time.time() + SIMULATION_DURATION
        
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
    
    await asyncio.sleep(SIMULATION_DURATION + 5)  # Tempo suficiente para processar todos os pacientes
    
    # ------------------------------------------------------------------------
    # 4. RELATÓRIO FINAL DETALHADO
    # ------------------------------------------------------------------------
    
    print("\n" + "=" * 60)
    print("📊 RELATÓRIO FINAL DO SISTEMA")
    print("=" * 60)
    
    # Estatísticas por hospital
    total_patients_treated = 0
    total_patients_rejected = 0
    total_discharged = 0
    total_discharge_time = 0.0
    total_treated_by_type = {"emergency": 0, "routine": 0}
    total_rejected_by_reason: Dict[str, int] = {}

    hospitals = [hospital1, hospital2, hospital3]
    now = time.time()
    for i, hospital in enumerate(hospitals, 1):
        print(f"\n🏥 HOSPITAL {i} ({hospital.name}):")
        print(f"   📋 Pacientes admitidos: {hospital.patients_treated}")
        print(f"   ❌ Pacientes rejeitados: {hospital.patients_rejected}")
        print(f"   🔄 Altas realizadas: {hospital.patients_discharged}")
        print(f"   🛏️  Camas: {hospital.beds_available}/{hospital.beds_total} disponíveis")
        print(f"   👥 Staff: {hospital.staff_available}/{hospital.staff_total} disponível")
        print(f"   📦 Supplies: {hospital.supplies_available}/{hospital.supplies_total} disponível")

        if hospital.patients_treated_by_type:
            by_type = ", ".join(
                f"{tipo}: {qtd}" for tipo, qtd in hospital.patients_treated_by_type.items()
            )
            print(f"   🧮 Tratados por tipo: {by_type}")

        if hospital.patients_rejected_by_reason:
            by_reason = ", ".join(
                f"{motivo}: {qtd}" for motivo, qtd in hospital.patients_rejected_by_reason.items()
            )
            print(f"   🚫 Rejeições por motivo: {by_reason}")

        if hospital.patients:
            print(f"   👤 Pacientes internados agora:")
            for patient in hospital.patients:
                severity_text = SEVERITY_LABELS.get(patient.severity, str(patient.severity))
                remaining = max(0.0, patient.length_of_stay - (now - patient.admission_time))
                print(
                    f"      • {patient.id} ({severity_text}, tipo {patient.patient_type}) "
                    f"→ alta em ~{remaining:.1f}s"
                )

        if hospital.patients_discharged:
            avg_stay = hospital.total_discharge_time / hospital.patients_discharged
            print(f"   ⏱️ Tempo médio de internamento: {avg_stay:.1f}s")

        total_patients_treated += hospital.patients_treated
        total_patients_rejected += hospital.patients_rejected
        total_discharged += hospital.patients_discharged
        total_discharge_time += hospital.total_discharge_time

        for tipo, qtd in hospital.patients_treated_by_type.items():
            total_treated_by_type[tipo] = total_treated_by_type.get(tipo, 0) + qtd

        for motivo, qtd in hospital.patients_rejected_by_reason.items():
            total_rejected_by_reason[motivo] = total_rejected_by_reason.get(motivo, 0) + qtd

    # Métricas globais
    print(f"\n📈 MÉTRICAS GLOBAIS:")
    print(f"   ✅ Total de pacientes tratados: {total_patients_treated}")
    print(f"   ❌ Total de pacientes rejeitados: {total_patients_rejected}")
    print(f"   🔄 Total de altas: {total_discharged}")
    if total_discharged:
        global_avg_stay = total_discharge_time / total_discharged
        print(f"   ⏱️ Tempo médio de internamento global: {global_avg_stay:.1f}s")

    total_patients = total_patients_treated + total_patients_rejected
    if total_patients > 0:
        success_rate = (total_patients_treated / total_patients) * 100
        print(f"   📊 Taxa de sucesso global: {success_rate:.1f}%")
    else:
        print(f"   📊 Taxa de sucesso global: N/A (nenhum paciente processado)")

    print(
        f"   📌 Tratados por tipo: "
        + ", ".join(f"{tipo}={qtd}" for tipo, qtd in total_treated_by_type.items())
    )
    if total_rejected_by_reason:
        print(
            f"   🚫 Rejeições por motivo: "
            + ", ".join(f"{motivo}={qtd}" for motivo, qtd in total_rejected_by_reason.items())
        )

    # Utilização de recursos
    total_beds = sum(h.beds_total for h in hospitals)
    total_available_beds = sum(h.beds_available for h in hospitals)
    beds_utilization = ((total_beds - total_available_beds) / total_beds) * 100

    print(f"   🛏️  Utilização de camas: {beds_utilization:.1f}%")

    # Estatísticas das ambulâncias
    print("\n🚑 MÉTRICAS DAS AMBULÂNCIAS:")
    total_requeued_patients = 0
    total_fulfilled_after_retry = 0
    total_transport_sum = 0.0
    total_successful_transports = 0

    for ambulance in [ambulance1, ambulance2]:
        summary = ambulance.behaviour_summary or {}
        print(f"\n   • {ambulance.name}")
        print(
            f"     Pacientes processados: {ambulance.total_patients_processed}"
            f" | Tratados: {summary.get('patients_treated', 0)}"
            f" | Rejeitados: {summary.get('patients_rejected', 0)}"
        )
        print(
            f"     Gerados por tipo: "
            + ", ".join(f"{tp}={qt}" for tp, qt in ambulance.generated_by_type.items())
        )
        if ambulance.rejections_by_reason:
            print(
                f"     Rejeições por motivo: "
                + ", ".join(f"{motivo}={qtd}" for motivo, qtd in ambulance.rejections_by_reason.items())
            )
        avg_time = summary.get("avg_transport_time", 0)
        success_rate = summary.get("success_rate", 0)
        print(f"     Tempo médio de transporte: {avg_time:.2f}s | Taxa de sucesso: {success_rate:.1f}%")
        print(
            f"     Reencaminhados: {ambulance.retry_queue_stats['requeued']} "
            f"| Cumpridos após reencaminho: {ambulance.retry_queue_stats['fulfilled']}"
        )
        total_requeued_patients += ambulance.retry_queue_stats["requeued"]
        total_fulfilled_after_retry += ambulance.retry_queue_stats["fulfilled"]
        total_transport_sum += ambulance.total_transport_time
        total_successful_transports += summary.get("patients_treated", 0)
        print(f"     Eventos em massa: {ambulance.mass_events_triggered}")

    if total_successful_transports:
        global_transport_avg = total_transport_sum / total_successful_transports
    else:
        global_transport_avg = 0.0

    print(
        f"\n   ➕ Totais das ambulâncias: reencaminhados={total_requeued_patients}, "
        f"cumpridos_após_reencaminho={total_fulfilled_after_retry}, "
        f"tempo_médio_transporte_global={global_transport_avg:.2f}s"
    )

    # Limpar recursos
    await hospital1.stop()
    await hospital2.stop()
    await hospital3.stop()
    
    print("\n🏁 Simulação terminada com sucesso!")
    print("=" * 60)


if __name__ == "__main__":
    spade.run(main(), embedded_xmpp_server=True)
