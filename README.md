# Observatório SNMP

Aplicativo desktop em Python/Tkinter para acompanhar CPU e tráfego de uma interface de roteador exclusivamente por SNMP v2c. Os dados coletados são armazenados localmente em SQLite para consulta histórica.

## Requisitos

- Python 3.10 ou superior
- Tkinter instalado (em Debian/Ubuntu: `sudo apt install python3-tk`)
- Acesso SNMP v2c habilitado no roteador e conectividade UDP para a porta configurada (padrão 161)
- A comunidade SNMP informada deve permitir leitura de IF-MIB e do OID de CPU suportado pelo roteador

## Instalação e execução

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Informe o IP do roteador, comunidade e porta e pressione **Descobrir**. A aplicação procura a interface cujo endereço está na mesma sub-rede IPv4 usada pelo computador para alcançar o roteador. Confira a seleção antes de iniciar; alguns roteadores não expõem seus endereços na tabela IP-MIB e, nesse caso, selecione a interface correta manualmente.

O intervalo de coleta é configurável em segundos. O painel em tempo real mantém uma janela deslizante de dez minutos. A aba Histórico consulta os dados armazenados por intervalo de data/hora local (`AAAA-MM-DD HH:MM`).

## CPU e tráfego SNMP

- CPU usa por padrão `HOST-RESOURCES-MIB::hrProcessorLoad` (`1.3.6.1.2.1.25.3.3.1.2`), apresentada como média dos processadores reportados.
- Tráfego usa contadores de 64 bits `IF-MIB::ifHCInOctets` e `ifHCOutOctets`, com fallback para os contadores de 32 bits da IF-MIB. As linhas exibem taxas em bytes por segundo calculadas pela diferença entre coletas.
- Cada fabricante pode expor CPU em OID próprio. O valor pode ser alterado em `~/.roteador_snmp_monitor/config.json`, no campo `cpu_oid`; o agente SNMP precisa responder com valores percentuais.
- A descoberta automática da interface usa IP-MIB e os endereços locais da máquina; ela é uma sugestão, não uma garantia para topologias com NAT, VLAN ou endereços não anunciados pelo roteador.

## Alertas

Os limites de CPU (%) e tráfego (MB/s) são configuráveis. O alerta é emitido quando a medida cruza o limite para cima e volta a disparar depois que cair abaixo dele.

- **Popup** mostra uma janela no desktop.
- **Email** requer destinatário, servidor SMTP, porta e remetente. Se o servidor exigir autenticação, a senha é solicitada no momento do envio e não é salva. O envio usa STARTTLS.

## Dados e testes

Configuração e banco ficam em `~/.roteador_snmp_monitor/`. Execute os testes sem um roteador real com:

```bash
python -m unittest discover -s tests -v
```