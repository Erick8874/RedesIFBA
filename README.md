# Observatório SNMP

Aplicativo desktop em Python/Tkinter para acompanhar CPU e tráfego de uma interface de roteador via SNMPv2c ou SNMPv3. A coleta contínua pode ser iniciada, pausada/retomada, encerrada e resetada apenas para visualização. As amostras são armazenadas localmente em SQLite para consulta histórica.

## Requisitos

- Python 3.10 ou superior
- Tkinter instalado (em Debian/Ubuntu: `sudo apt install python3-tk`)
- Acesso SNMPv3 ou SNMPv2c habilitado no roteador e conectividade UDP para a porta configurada (padrão 161)
- Em SNMPv2c, use uma comunidade somente leitura e permita acesso à IF-MIB e ao OID de CPU suportado pelo roteador. Restrinja UDP/161 aos endereços necessários.
- Prefira SNMPv3 em redes reais. A aplicação usa autenticação SHA e, opcionalmente, privacidade AES-128; SNMPv2c fica disponível para laboratórios isolados.

## Instalação e execução

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

No Windows, use PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Informe o IP do roteador, versão SNMP e porta e pressione **Descobrir**. Para v2c, informe a comunidade de leitura. Para v3, informe usuário e chave de autenticação (mínimo de 8 caracteres); chave de privacidade é opcional. A chave de autenticação usa SHA e a chave de privacidade usa AES-128. A aplicação procura a interface cujo endereço está na mesma sub-rede IPv4 usada pelo computador para alcançar o roteador. Confira a seleção antes de iniciar; alguns roteadores não expõem seus endereços na tabela IP-MIB e, nesse caso, selecione a interface correta manualmente.

O intervalo de coleta é configurável em segundos. O painel em tempo real mantém uma janela deslizante de dez minutos. **Pausar** preserva a série; **Iniciar** retoma a coleta pausada. **Resetar visualização** limpa somente a série em tempo real exibida, não apaga o histórico persistido. **Encerrar** termina a coleta. A aba Histórico consulta os dados armazenados por intervalo de data/hora local (`AAAA-MM-DD HH:MM`) e informa quando não há amostras.

## CPU e tráfego SNMP

- CPU usa por padrão `HOST-RESOURCES-MIB::hrProcessorLoad` (`1.3.6.1.2.1.25.3.3.1.2`), apresentada como média dos processadores reportados.
- Tráfego usa contadores de 64 bits `IF-MIB::ifHCInOctets` (`1.3.6.1.2.1.31.1.1.1.6`) e `ifHCOutOctets` (`1.3.6.1.2.1.31.1.1.1.10`), com fallback para `ifInOctets` (`1.3.6.1.2.1.2.2.1.10`) e `ifOutOctets` (`1.3.6.1.2.1.2.2.1.16`). Taxa em bps = diferença dos contadores em bytes × 8 / intervalo real medido com relógio monotônico. A coleta inicial mostra 0 bps por não haver contador anterior. Reinicializações ou quedas inesperadas do contador são descartadas como 0 bps; wrap de contador só é aceito perto do limite numérico. Amostras antigas salvas em bytes/s são convertidas para bps na inicialização do repositório.
- Cada fabricante pode expor CPU em OID próprio. O valor pode ser alterado em `~/.roteador_snmp_monitor/config.json`, no campo `cpu_oid`; o agente SNMP precisa responder com valores percentuais.
- A descoberta automática da interface usa IP-MIB e os endereços locais da máquina; ela é uma sugestão, não uma garantia para topologias com NAT, VLAN ou endereços não anunciados pelo roteador.

## Alertas

Os limites de CPU (%) e tráfego (bps) são configuráveis. O mesmo threshold de tráfego é comparado separadamente com IN e OUT. O alerta é emitido na transição de normal para excedido e volta a disparar depois que a métrica cair abaixo do limite. Cada notificação inclui métrica, valor observado, limite e horário.

- **popup**, **email** ou **both** permitem selecionar pop-up, email ou ambos.
- Email requer endereço de destino válido, servidor SMTP, porta e remetente. Se o servidor exigir autenticação, a senha é solicitada no momento do envio e não é salva. O envio usa STARTTLS. Erros de envio e de coleta são apresentados no status da aplicação sem encerrar o monitoramento.

## Configuração e persistência

Os parâmetros são salvos em `~/.roteador_snmp_monitor/config.json`, e o histórico em `~/.roteador_snmp_monitor/historico.sqlite3`. O arquivo de configuração contém comunidade e, se usado SNMPv3, as chaves do usuário; mantenha-o fora de repositórios, limite as permissões de leitura e proteja o acesso à conta local. O endereço do roteador, versão/credenciais SNMP, porta, índice da interface e OID de CPU também podem ser definidos nesse arquivo. O campo `cpu_oid` usa por padrão `1.3.6.1.2.1.25.3.3.1.2` (HOST-RESOURCES-MIB `hrProcessorLoad`).

## Arquitetura

- `snmp_client.py` consulta OIDs SNMPv2c/v3, valida CPU e contadores e calcula as taxas.
- `repository.py` persiste as amostras em SQLite e consulta intervalos temporais; configurações antigas do banco são migradas.
- `alerts.py` avalia as transições de threshold e envia notificações SMTP via STARTTLS.
- `ui.py` mantém a interface Tkinter, worker de coleta, gráficos Matplotlib, controles e apresentação de falhas.

## Testes mínimos

- **Coleta/recuperação:** iniciar com SNMP acessível; confirmar taxas IN/OUT em bps e CPU em %, interromper o acesso e confirmar erro no status e recuperação após restabelecer.
- **Controles:** iniciar repetidamente não cria outro worker; pausar e retomar mantém dados; resetar limpa a visualização mas preserva o histórico.
- **Histórico:** filtrar dois horários e confirmar contagem e dados do período; testar intervalo sem amostras e reiniciar o aplicativo para verificar persistência.
- **Alertas:** configurar valores baixos para testar pop-up, email e ambos; verificar mensagem com métrica/valor/limite/horário e novo alerta após recuperação.
- **Validação:** testar intervalo zero, endereço de email inválido, interface/OID inexistente e indisponibilidade SMTP.

Execute os testes sem um roteador real com:

```bash
python -m unittest discover -s tests -v
```