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

# validation db and redis passwords
if (ARGV & %w[up provision reload]).any? && (get_env("DB_PASSWORD").nil? || get_env("REDIS_PASSWORD").nil?)
  abort "DB_PASSWORD or REDIS_PASSWORD is missing. Copy .env.example to .env and set them."
end

# --- network
BOX = get_env("VAGRANT_BOX", "bento/ubuntu-22.04")
LAN_PREFIX = get_env("LAN_PREFIX", "192.168.0")
NETMASK = "255.255.255.0"
BRIDGE = get_env("BRIDGE_INTERFACE")
HOST_NUMBERS = {
  "db"      => 50,
  "fetcher" => 51,
  "history" => 52,
  "ui"      => 53,
}.freeze

def ip_of(name)
  "#{LAN_PREFIX}.#{HOST_NUMBERS.fetch(name)}"
end

HISTORY_PORT = get_env("HISTORY_PORT", "8002")
DB_PORT = get_env("DB_PORT", "5432")
REDIS_PORT = get_env("REDIS_PORT", "6379")

# Dockerfile folder inside the VM
APP_ROOT = "/opt/citybikes"

SYNC_EXCLUDE = [".venv/", "venv/", "node_modules/", "dist/", "__pycache__/", "test_*.py"].freeze

# Flags for the app containers: no Linux capabilities, root filesystem read-only
# where the app does not need to write (/tmp is a tmpfs).
HARDEN = "--cap-drop ALL"
READ_ONLY = "#{HARDEN} --read-only --tmpfs /tmp"

# --- VMs: one VM = one list of containers (each built from its own Dockerfile).
# To add a service: add an entry here (and a Dockerfile). No copy-pasted VM blocks.
#   context : folder with the Dockerfile      publish : "host_port:container_port"
#   volume  : named volume for data           env     : variables the container gets at start
VMS = [
  {
    name: "db",
    ip: ip_of("db"),
    cpus: 1,
    memory: 1024,
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
          "ALLOWED_CIDR"      => get_env("ALLOWED_CIDR", "#{LAN_PREFIX}.0/24").to_s,
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
    ],
  },
  {
    name: "fetcher",
    ip: ip_of("fetcher"),
    cpus: 1,
    memory: 1024,
    containers: [
      {
        name: "fetcher",
        context: "services/fetcher",
        run_args: READ_ONLY,
        env: {
          "REDIS_HOST"           => ip_of("db"),
          "REDIS_PORT"           => REDIS_PORT,
          "REDIS_PASSWORD"       => get_env("REDIS_PASSWORD").to_s,
          "CITYBIKES_NETWORK_ID" => get_env("CITYBIKES_NETWORK_ID", "pittsburgh").to_s,
        },
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
          "DB_HOST"        => ip_of("db"),
          "DB_PORT"        => DB_PORT,
          "DB_NAME"        => get_env("DB_NAME", "citybikes").to_s,
          "DB_USER"        => get_env("DB_USER", "citybikes_app").to_s,
          "DB_PASSWORD"    => get_env("DB_PASSWORD").to_s,
          "REDIS_HOST"     => ip_of("db"),
          "REDIS_PORT"     => REDIS_PORT,
          "REDIS_PASSWORD" => get_env("REDIS_PASSWORD").to_s,
          "POLL_INTERVAL"  => get_env("POLL_INTERVAL", "60").to_s,
        },
      },
    ],
  },
  {
    name: "ui",
    ip: ip_of("ui"),
    cpus: 1,
    memory: 1024,
    message: "==> citybikes-ui is up. Open http://#{ip_of('ui')} (from any device in your LAN)",
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
    ],
  },
].freeze

# the variables run-container.sh needs for one container
def container_env(c)
  c[:env].merge(
    "CONTAINER_NAME" => c[:name],
    "BUILD_DIR"      => "#{APP_ROOT}/#{c[:name]}",
    "ENV_KEYS"       => c[:env].keys.join(" "),
    "PUBLISH"        => c[:publish].to_s,
    "VOLUME"         => c[:volume].to_s,
    "RUN_ARGS"       => c[:run_args].to_s,
  )
end

# --- build
Vagrant.configure("2") do |config|
  config.vm.box = BOX
  config.vm.box_check_update = false

  # DO NOT synchronize the actual dir with the VMs vagrant dir
  config.vm.synced_folder ".", "/vagrant", disabled: true

  VMS.each do |vm|
    config.vm.define vm[:name] do |node|
      node.vm.hostname = "citybikes-#{vm[:name]}"

      # bridged: a real address in your LAN
      net_opts = { ip: vm[:ip], netmask: NETMASK }
      net_opts[:bridge] = BRIDGE if BRIDGE
      node.vm.network "public_network", **net_opts

      node.vm.provider "virtualbox" do |vb|
        vb.name   = "citybikes-#{vm[:name]}"
        vb.cpus   = vm[:cpus]
        vb.memory = vm[:memory]
      end

      # code + Dockerfile copying to VM
      vm[:containers].each do |c|
        node.vm.synced_folder c[:context], "#{APP_ROOT}/#{c[:name]}", type: "rsync", rsync__exclude: SYNC_EXCLUDE
      end

      # 2. enabling docker
      node.vm.provision "docker", type: "shell", path: "provision/docker.sh"

      # build image + start its container 
      vm[:containers].each do |c|
        node.vm.provision "app-#{c[:name]}", type: "shell", path: "provision/run-container.sh", env: container_env(c)
      end

      node.vm.post_up_message = vm[:message] || "==> citybikes-#{vm[:name]} is at #{vm[:ip]}"
    end
  end
end
