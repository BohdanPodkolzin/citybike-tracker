require "base64"

# dotenv reader
def load_dotenv(path)
  return {} unless File.exist?(path)
  File.readlines(path, chomp: true).each_with_object({}) do |line, vars|
    line = line.strip
    next if line.empty? || line.start_with?("#")
    key, value = line.split("=", 2)
    next if value.nil?
    vars[key.strip] = value.strip.sub(/\A(["'])(.*)\1\z/, '\2')
  end
end

DOTENV = load_dotenv(File.join(__dir__, ".env"))

def get_env(key, default = nil)
  value = ENV[key] || DOTENV[key] || default
  value.to_s.empty? ? nil : value.to_s
end

# the three backends always run on the db VM, so all three passwords are needed
if (ARGV & %w[up provision reload]).any?
  missing = %w[DB_PASSWORD REDIS_PASSWORD RABBITMQ_PASSWORD].select { |k| get_env(k).nil? }
  abort "#{missing.join(', ')} missing. Copy .env.example to .env and set them." unless missing.empty?
end

QUEUE_BACKEND = get_env("QUEUE_BACKEND", "rabbitmq").downcase   # rabbitmq | postgres
CACHE_BACKEND = get_env("CACHE_BACKEND", "redis").downcase      # redis | postgres
abort "QUEUE_BACKEND must be rabbitmq or postgres, got #{QUEUE_BACKEND}" unless %w[rabbitmq postgres].include?(QUEUE_BACKEND)
abort "CACHE_BACKEND must be redis or postgres, got #{CACHE_BACKEND}" unless %w[redis postgres].include?(CACHE_BACKEND)

SSH_KEY_FILE = File.expand_path(get_env("SSH_KEY_FILE", "~/.ssh/citybikes_ed25519"))
INTERNAL_KEY_FILE = File.expand_path(get_env("SSH_INTERNAL_KEY_FILE", "~/.ssh/citybikes_internal_ed25519"))
if (ARGV & %w[up provision reload]).any?
  lacking = ["#{SSH_KEY_FILE}.pub", INTERNAL_KEY_FILE, "#{INTERNAL_KEY_FILE}.pub"].reject { |f| File.exist?(f) }
  abort "#{lacking.join(', ')} not found. Run: bash scripts/setup-ssh.sh" unless lacking.empty?
end
def read_if_exists(path)
  File.exist?(path) ? File.read(path).strip : ""
end
USER_PUBKEY = read_if_exists("#{SSH_KEY_FILE}.pub")              # goes to the bastion
INTERNAL_PUBKEY = read_if_exists("#{INTERNAL_KEY_FILE}.pub")     # goes to every other VM
INTERNAL_KEY_B64 = Base64.strict_encode64(read_if_exists(INTERNAL_KEY_FILE) + "\n")  # goes to the bastion only

# --- network
BOX = get_env("VAGRANT_BOX", "bento/ubuntu-22.04")
LAN_PREFIX = get_env("LAN_PREFIX", "192.168.0")          # only ui and bastion join
PRIVATE_PREFIX = get_env("PRIVATE_PREFIX", "10.20.0")    # every VM
PRIVATE_NET = "citybikes-private"                        # VirtualBox internal network name
NETMASK = "255.255.255.0"
BRIDGE = get_env("BRIDGE_INTERFACE")
HOST_NUMBERS = {
  "db"      => 50,
  "fetcher" => 51,
  "history" => 52,
  "ui"      => 53,
  "bastion" => 54,
}.freeze

def ip_of(name)
  "#{PRIVATE_PREFIX}.#{HOST_NUMBERS.fetch(name)}"
end

def lan_ip_of(name)
  "#{LAN_PREFIX}.#{HOST_NUMBERS.fetch(name)}"
end

HISTORY_PORT = get_env("HISTORY_PORT", "8002")
DB_PORT = get_env("DB_PORT", "5432")
REDIS_PORT = get_env("REDIS_PORT", "6379")
RABBITMQ_PORT = get_env("RABBITMQ_PORT", "5672")
RABBITMQ_UI_PORT = "15672"
RABBITMQ_USER = get_env("RABBITMQ_USER", "citybikes")
RABBITMQ_VHOST = get_env("RABBITMQ_VHOST", "citybikes")
LOKI_PORT = get_env("LOKI_PORT", "3100")
GRAFANA_PORT = get_env("GRAFANA_PORT", "3000")
LOKI_URL = "http://#{ip_of('db')}:#{LOKI_PORT}"

# Dockerfile folder
APP_ROOT = "/opt/citybikes"
# not copied to the VMs: Docker rebuilds them there (the .dockerignore files cover the image)
SYNC_EXCLUDE = [".venv/", "venv/", "node_modules/", "dist/", "__pycache__/", "test_*.py"].freeze

HARDEN = "--cap-drop ALL"
READ_ONLY = "#{HARDEN} --read-only --tmpfs /tmp"

def db_env
  {
    "DB_HOST"     => ip_of("db"),
    "DB_PORT"     => DB_PORT,
    "DB_NAME"     => get_env("DB_NAME", "citybikes").to_s,
    "DB_USER"     => get_env("DB_USER", "citybikes_app").to_s,
    "DB_PASSWORD" => get_env("DB_PASSWORD").to_s,
  }
end

def queue_env
  return db_env if QUEUE_BACKEND == "postgres"   # the queue is a table: needs the database
  {
    "RABBITMQ_HOST"     => ip_of("db"),
    "RABBITMQ_PORT"     => RABBITMQ_PORT,
    "RABBITMQ_USER"     => RABBITMQ_USER,
    "RABBITMQ_PASSWORD" => get_env("RABBITMQ_PASSWORD").to_s,
    "RABBITMQ_VHOST"    => RABBITMQ_VHOST,
  }
end

def cache_env
  return {} if CACHE_BACKEND == "postgres"       # the cache is a table: History has the database anyway
  {
    "REDIS_HOST"     => ip_of("db"),
    "REDIS_PORT"     => REDIS_PORT,
    "REDIS_PASSWORD" => get_env("REDIS_PASSWORD").to_s,
  }
end

CLOUDFLARE_TUNNEL_TOKEN = get_env("CLOUDFLARE_TUNNEL_TOKEN")
def cloudflared_containers
  return [] if CLOUDFLARE_TUNNEL_TOKEN.nil?
  [
    {
      name: "cloudflared",
      context: "services/cloudflared",
      run_args: READ_ONLY,
      env: {
        "TUNNEL_TOKEN" => CLOUDFLARE_TUNNEL_TOKEN,
        # auto = QUIC (UDP 7844) with fallback; set http2 (TCP 443) if your network blocks UDP
        "TUNNEL_TRANSPORT_PROTOCOL" => get_env("CLOUDFLARE_TUNNEL_PROTOCOL", "auto").to_s,
      },
    },
  ]
end

VMS = [
  {
    name: "db",
    ip: ip_of("db"),
    cpus: 1,
    memory: 3072,
    containers: [
      {
        name: "postgres",
        context: "services/postgres",
        publish: "#{DB_PORT}:5432",
        volume: "citybikes-pgdata:/var/lib/postgresql/data",
        env: {
          "POSTGRES_DB"       => get_env("DB_NAME", "citybikes").to_s,
          "POSTGRES_USER"     => get_env("DB_USER", "citybikes_app").to_s,
          "POSTGRES_PASSWORD" => get_env("DB_PASSWORD").to_s,
          "ALLOWED_CIDR"      => get_env("ALLOWED_CIDR", "#{PRIVATE_PREFIX}.0/24").to_s,
        },
      },
      {
        name: "redis",
        context: "services/redis",
        publish: "#{REDIS_PORT}:6379",
        volume: "citybikes-redisdata:/data",
        env: {
          "REDIS_PASSWORD" => get_env("REDIS_PASSWORD").to_s,
        },
      },
      {
        name: "rabbitmq",
        context: "services/rabbitmq",
        hostname: "rabbitmq-citybikes",   # fixed: RabbitMQ ties its data to the node name
        publish: ["#{RABBITMQ_PORT}:5672", "#{RABBITMQ_UI_PORT}:15672"],
        volume: "citybikes-rabbitmqdata:/var/lib/rabbitmq",
        env: {
          "RABBITMQ_DEFAULT_USER"  => RABBITMQ_USER,
          "RABBITMQ_DEFAULT_PASS"  => get_env("RABBITMQ_PASSWORD").to_s,
          "RABBITMQ_DEFAULT_VHOST" => RABBITMQ_VHOST,
        },
      },
      {
        name: "loki",
        context: "services/loki",
        publish: "#{LOKI_PORT}:3100",
        volume: "citybikes-lokidata:/loki",
        run_args: HARDEN,
        env: {},   # no secrets, no settings: all of it is in services/loki/loki.yaml (7 days of logs)
      },
      {
        name: "grafana",
        context: "services/grafana",
        publish: "#{GRAFANA_PORT}:3000",
        volume: "citybikes-grafanadata:/var/lib/grafana",
        run_args: HARDEN,
        env: {
          "LOKI_URL"                  => LOKI_URL,
          "GF_SECURITY_ADMIN_USER"    => "admin",
          "GF_SECURITY_ADMIN_PASSWORD" => get_env("GRAFANA_PASSWORD").to_s,
          "GF_USERS_ALLOW_SIGN_UP"    => "false",
          "GF_AUTH_ANONYMOUS_ENABLED" => "false",
          "GF_ANALYTICS_REPORTING_ENABLED"       => "false",
          "GF_ANALYTICS_CHECK_FOR_UPDATES"       => "false",
          "GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH" => "/etc/grafana/dashboards/citybikes-logs.json",
        },
      },
    ],
  },
  {
    name: "fetcher",
    ip: ip_of("fetcher"),
    cpus: 1,
    memory: 768,
    containers: [
      {
        name: "fetcher",
        context: "services/fetcher",
        run_args: READ_ONLY,
        env: {
          "QUEUE_BACKEND"        => QUEUE_BACKEND,
          "CITYBIKES_NETWORK_ID" => get_env("CITYBIKES_NETWORK_ID", "pittsburgh").to_s,
        }.merge(queue_env),
      },
    ],
  },
  {
    name: "history",
    ip: ip_of("history"),
    cpus: 1,
    memory: 1024,
    containers: [
      {
        name: "history",
        context: "services/history",
        publish: "#{HISTORY_PORT}:8002",
        run_args: READ_ONLY,
        env: {
          "QUEUE_BACKEND" => QUEUE_BACKEND,
          "CACHE_BACKEND" => CACHE_BACKEND,
          "POLL_INTERVAL" => get_env("POLL_INTERVAL", "60").to_s,
        }.merge(db_env).merge(queue_env).merge(cache_env),
      },
    ],
  },
  {
    name: "ui",
    ip: ip_of("ui"),
    lan_ip: lan_ip_of("ui"),
    cpus: 1,
    memory: 1024,
    message: "==> citybikes-ui is up. Open http://#{lan_ip_of('ui')} (from any device in your LAN)",
    containers: [
      {
        name: "ui",
        context: "services/ui",
        publish: "80:8080",
        run_args: HARDEN,
        env: {
          "HISTORY_URL" => "http://#{ip_of('history')}:#{HISTORY_PORT}",
        },
      },
    ] + cloudflared_containers,
  },
  {
    # The only way in: ssh bastion, then from it to every other VM (see README). No containers.
    name: "bastion",
    ip: ip_of("bastion"),
    lan_ip: lan_ip_of("bastion"),
    cpus: 1,
    memory: 768,
    containers: [],
    message: "==> bastion is at #{lan_ip_of('bastion')}. Log in:  ssh bastion   then from it:  ssh ui | ssh fetcher | ssh history | ssh db",
  },
].freeze

def log_agent_for(vm)
  {
    name: "log-agent",
    context: "services/log-agent",
    volume: "citybikes-alloydata:/var/lib/alloy/data",
    run_args: "--user 0 #{READ_ONLY} --cap-add DAC_OVERRIDE " \
              "-v /var/run/docker.sock:/var/run/docker.sock:ro " \
              "-v /var/log/journal:/var/log/journal:ro -v /run/log/journal:/run/log/journal:ro " \
              "-v /etc/machine-id:/etc/machine-id:ro",
    env: {
      "VM_NAME"       => vm[:name],
      "LOKI_PUSH_URL" => "#{LOKI_URL}/loki/api/v1/push",
    },
  }
end


# the variables run-container.sh needs for one container
def container_env(cont)
  cont[:env].merge(
    "CONTAINER_NAME" => cont[:name],
    "BUILD_DIR"      => "#{APP_ROOT}/#{cont[:name]}",
    "ENV_KEYS"       => cont[:env].keys.join(" "),
    "PUBLISH"        => Array(cont[:publish]).join(" "),
    "CONTAINER_HOSTNAME" => cont[:hostname].to_s,
    "VOLUME"         => cont[:volume].to_s,
    "RUN_ARGS"       => cont[:run_args].to_s,
  )
end

# --- build
Vagrant.configure("2") do |config|
  config.vm.box = BOX
  config.vm.box_check_update = false
  # four VMs on one laptop can boot slowly: wait up to 10 minutes for SSH
  config.vm.boot_timeout = 600

  # DO NOT synchronize the actual dir with the VMs vagrant dir
  config.vm.synced_folder ".", "/vagrant", disabled: true

  VMS.each do |vm|
    containers = vm[:containers] + [log_agent_for(vm)]
    config.vm.define vm[:name] do |node|
      node.vm.hostname = "citybikes-#{vm[:name]}"

      node.vm.network "private_network", ip: vm[:ip], netmask: NETMASK, virtualbox__intnet: PRIVATE_NET

      if vm[:lan_ip]
        net_opts = { ip: vm[:lan_ip], netmask: NETMASK }
        net_opts[:bridge] = BRIDGE if BRIDGE
        node.vm.network "public_network", **net_opts
      end

      node.vm.provider "virtualbox" do |vb|
        vb.name   = "citybikes-#{vm[:name]}"
        vb.cpus   = vm[:cpus]
        vb.memory = vm[:memory]
      end

      # 1. the build contexts (Dockerfile + code) are copied into the VM
      containers.each do |c|
        node.vm.synced_folder c[:context], "#{APP_ROOT}/#{c[:name]}", type: "rsync", rsync__exclude: SYNC_EXCLUDE
      end

      # 2. Docker + journalctl disk storage enabled at boot
      node.vm.provision "docker", type: "shell", path: "provision/docker.sh"
      node.vm.provision "journal", type: "shell", path: "provision/journal.sh"

      # 3. build every image and start its container
      containers.each do |c|
        node.vm.provision "app-#{c[:name]}", type: "shell", path: "provision/run-container.sh", env: container_env(c)
      end

      bastion = vm[:name] == "bastion"
      ssh_env = {
        "ROLE"        => bastion ? "bastion" : "target",
        "AUTH_PUBKEY" => bastion ? USER_PUBKEY : INTERNAL_PUBKEY,   # whose key this VM accepts
        "BASTION_IP"  => ip_of("bastion"),
      }
      if bastion
        ssh_env["INTERNAL_KEY_B64"] = INTERNAL_KEY_B64
        ssh_env["PRIVATE_HOSTS"] = HOST_NUMBERS.reject { |n, _| n == "bastion" }.map { |n, _| "#{n}=#{ip_of(n)}" }.join(" ")
      end
      node.vm.provision "ssh-access", type: "shell", path: "provision/ssh-access.sh", env: ssh_env

      node.vm.post_up_message = vm[:message] || "==> citybikes-#{vm[:name]} is at #{vm[:ip]}"
    end
  end
end
